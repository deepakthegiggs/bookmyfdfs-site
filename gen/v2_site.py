"""Site v2 preview (decision 171): the whole site rebuilt dark-first and phone-first under /v2/, from the same checked
data and the same guards as the live site. Built next to the live pages, never instead of them:

- every v2 page is noindex,nofollow, its canonical points at the live page it will replace (or at itself when there is
  none yet), and no v2 URL goes in the sitemap, the feeds, llms.txt, search.json, the build state or .changed-urls.txt;
- the paths are "/v2" + the live path, so switching later is a prefix drop;
- one stylesheet (/assets/v2.css), one script (/assets/v2.js) and one data file (/v2/data.json), all cached;
- "My cards", Saved, the monthly-use tracker and the savings diary live in localStorage on this device. My cards and
  Saved share the live site's keys (fdfs.cards.v1, fdfs.saved.v1), so a visitor's picks carry over.

Real checked offers only; spotted leads are dashed, labelled and never counted with them. No popularity counts, no
countdown that isn't a real end date, no platform price comparison, no fetching booking sites, no logos.
Kept out of fdfs_site.py so parallel work there merges cleanly. fdfs_site binds itself as `g` at import."""
from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

g = None   # fdfs_site, bound by fdfs_site at import (avoids a circular import)

V2 = "/v2"
HERE = Path(__file__).resolve().parent
CALC_PATH = "/tools/which-offer-works/"
MY_PATH = "/my/"
OFFERS_PATH = "/offers/"


def E(s) -> str:
    return g.E(str(s))


def vp(path: str) -> str:
    return V2 + path


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def nice(v: str) -> str:
    return v.title() if v.isupper() or v.islower() else v


def who_nice(o) -> str:
    w = g.who(o)
    for v in o.variants:
        if v.isupper() and len(v) > 4:
            w = w.replace(v, v.title())
    return w


def app_k(o) -> str:
    return g.app_key(o.platform) or "cinema"


def plain_app(o) -> str:
    return g.where(o).split(" · ")[0]


def free_cap(o) -> int:
    return g.cap_num(o)


# ---------------------------------------------------------------- what the browser reads (data.json)
def card_ids(o) -> tuple[list, str]:
    """(match ids, scope). Listed variants match only those exact products; an unstated or all-cards scope matches any
    card the visitor holds from that bank (marked "check your card is included" when unstated)."""
    bid = g.bank_id(o.issuer)
    if o.variants_scope == "listed" and o.variants:
        return [f"{bid}:{slug(v)}" for v in o.variants], "listed"
    return ["*" + bid], o.variants_scope or "unstated"


def need(o) -> int:
    """Tickets one booking needs: the terms' minimum, else 2 for a second-ticket offer (by definition), else 1."""
    return o.min_tickets or (2 if o.kind == "bogo" else 1)


def row(site, o, today: date) -> dict:
    bid = g.bank_id(o.issuer)
    ids, scope = card_ids(o)
    hr = o.raw.get("how_to_redeem") or {}
    spend = g.spend_gate(o.quota_note)
    return {
        "id": o.id, "bank": bid, "bankName": site.bank_name(o.issuer), "who": who_nice(o), "what": g.what(o),
        "cap": g.cap(o), "capNum": free_cap(o), "app": app_k(o), "appName": g.app_name(o), "where": plain_app(o),
        "movie": o.is_movie, "kind": o.kind, "pct": (o.value or {}).get("pct"),
        "days": [d for d in o.days if d == "any" or d in g.DAY_IDX], "basis": o.day_basis,
        "from": o.valid_from.isoformat() if o.valid_from else None,
        "to": o.valid_to.isoformat() if o.valid_to else None,
        "spend": spend, "min": o.min_tickets, "monthly": o.monthly_limit,
        "times": g.times(o.monthly_limit) if o.monthly_limit else None, "code": o.code,
        "redeem": hr.get("label") if hr.get("method") == "pick_offer" else None,
        "checked": g.fmt_stamp(o.checked_at), "checkedAt": g.iso(o.checked_at),
        "terms": (o.terms_urls or [o.source_url])[-1], "page": vp(g.offer_path(o.id)),
        "matches": ids, "scope": scope, "network": o.raw.get("network"), "instrument": o.instrument,
    }


def wallet_cards(site, offers: list) -> list:
    """The pickable cards: each exact product a checked offer lists, plus "Another <bank> card" per bank."""
    out, seen = [], set()
    for o in sorted(offers, key=lambda x: (g.bank_id(x.issuer), x.id)):
        if not o.is_bank:
            continue
        bid = g.bank_id(o.issuer)
        if o.variants_scope == "listed":
            for v in o.variants:
                cid = f"{bid}:{slug(v)}"
                if cid not in seen:
                    seen.add(cid)
                    kind = "credit card" if o.instrument == "credit" else "debit card" if o.instrument == "debit" else "card"
                    out.append({"id": cid, "bank": bid, "label": f"{o.issuer} {nice(g.clean_variant(o.issuer, v))} {kind}"})
    for bid in sorted({g.bank_id(o.issuer) for o in offers if o.is_bank}):
        name = next(site.bank_name(o.issuer) for o in offers if g.bank_id(o.issuer) == bid)
        out.append({"id": bid, "bank": bid, "label": f"Another {name} card", "other": True})
    return out


# ---------------------------------------------------------------- pieces of HTML
ICONS = {
    "home": '<path d="M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    "list": '<path d="M7 5.5h10M7 10h10M7 14.5h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="3.6" cy="5.5" r="1.2" fill="currentColor"/><circle cx="3.6" cy="10" r="1.2" fill="currentColor"/><circle cx="3.6" cy="14.5" r="1.2" fill="currentColor"/>',
    "week": '<rect x="2.5" y="4" width="15" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M2.5 8.5h15M6.5 2v3.5M13.5 2v3.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
    "heart": '<path d="M10 16.5s-6.5-3.9-6.5-8.6A3.6 3.6 0 0 1 10 6a3.6 3.6 0 0 1 6.5 1.9c0 4.7-6.5 8.6-6.5 8.6z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    "card": '<rect x="2" y="4.5" width="16" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M2 8.5h16" stroke="currentColor" stroke-width="2"/>',
}


def ico(name: str) -> str:
    return f'<svg class="i" viewBox="0 0 20 20" aria-hidden="true">{ICONS[name]}</svg>'


def chips(o, today: date) -> str:
    out = []
    for cls, text, attrs in g.cond_chips(o, today):
        if "c-app" in cls:
            continue
        c = "ok" if "today-ok" in cls else "wait" if "today-wait" in cls else "none" if "today-none" in cls else \
            "key" if "c-key" in cls else "end" if "c-end" in cls else ""
        out.append(f'<li{f" class={chr(34)}{c}{chr(34)}" if c else ""}{attrs}>{E(text)}</li>')
    return f'<ul class="ch">{"".join(out)}</ul>'


def day_attr(o) -> str:
    if "any" in o.days:
        return "any"
    return " ".join(g.day_keys(o))


def offer_card(site, o, today: date, h: str = "h3") -> str:
    bid = g.bank_id(o.issuer)
    end = o.valid_to.isoformat() if o.valid_to else ""
    spend = "1" if g.spend_gate(o.quota_note) else "0"
    terms = (o.terms_urls or [o.source_url])[-1]
    return (f'<article class="oc" id="o-{E(o.id)}" data-id="{E(o.id)}" data-bank="{E(bid)}" data-app="{app_k(o)}" '
            f'data-kind="{E(o.kind)}" data-cap="{free_cap(o)}" data-end="{end}" data-checked="{g.iso(o.checked_at)}" '
            f'data-movie="{1 if o.is_movie else 0}" data-days="{day_attr(o)}" data-spend="{spend}" '
            f'data-t="{E((who_nice(o) + " " + site.bank_name(o.issuer) + " " + g.app_name(o) + " " + g.what(o)).lower())}">'
            f'<div class="oc-top">{g.monogram(bid, o.issuer)}<div class="oc-id"><p class="oc-who">{E(who_nice(o))}</p>'
            f'<p class="oc-app">{E(g.where(o))}</p></div>'
            f'<button class="sv js" type="button" data-save="{E(o.id)}" aria-pressed="false">{ico("heart")}'
            f'<span class="sr">Save the {E(who_nice(o))} offer</span></button></div>'
            f'<{h} class="oc-what"><a href="{vp(g.offer_path(o.id))}">{E(g.what(o))} <span class="oc-cap">{E(g.cap(o))}</span></a></{h}>'
            f'{chips(o, today)}<p class="oc-ft"><span>Checked {E(g.fmt_dm(o.checked_at.astimezone(g.IST).date()))}</span>'
            f'<span class="fit js" hidden></span>{g.ext(terms, "Terms" + g.icon("out"), cls="tl", sr="official terms")}</p></article>')


def offer_list(site, offers: list, today: date, h: str = "h3", lid: str = "") -> str:
    if not offers:
        return '<p class="empty">No checked offer here right now.</p>'
    return (f'<div class="ol"{f" id={chr(34)}{lid}{chr(34)}" if lid else ""}>'
            + "".join(offer_card(site, o, today, h) for o in offers) + "</div>")


def order(offers: list) -> list:
    return sorted(offers, key=lambda o: (not o.is_movie, -free_cap(o), o.id))


def usable_on(o, d: date) -> bool:
    if not o.is_movie or (o.valid_from and d < o.valid_from) or (o.valid_to and d > o.valid_to):
        return False
    if "any" in o.days or not o.days:
        return True
    k = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[d.weekday()]
    return k in o.days


def week_strip(offers: list, today: date) -> str:
    cells = []
    for i in range(7):
        d = today + timedelta(days=i)
        best = sorted([o for o in offers if usable_on(o, d)], key=lambda o: (-free_cap(o), o.id))
        lab = d.strftime("%a")
        if best:
            b = best[0]
            inner = (f'<span class="wd-d" data-dl>{lab} <b>{d.day}</b></span><span class="wd-c">{E("up to ₹" + format(free_cap(b), ",")) if free_cap(b) else E(g.what(b))}</span>'
                     f'<span class="wd-w">{E(who_nice(b))}</span>')
        else:
            inner = f'<span class="wd-d" data-dl>{lab} <b>{d.day}</b></span><span class="wd-c wd-0">No offer</span><span class="wd-w">&nbsp;</span>'
        cells.append(f'<li><a class="wd" href="{vp("/this-week/")}#d-{d.isoformat()}" data-date="{d.isoformat()}">{inner}</a></li>')
    return f'<ol class="wk" aria-label="Best checked offer on each of the next 7 days">{"".join(cells)}</ol>'


def faq(items: list) -> str:
    return '<div class="faq">' + "".join(
        f'<details><summary><h3>{E(q)}</h3></summary><div class="fa">{a}</div></details>' for q, a in items) + "</div>"


# ---------------------------------------------------------------- the page shell
class V:
    """One v2 page. `live` is the live path it will replace (canonical), or None for a page that has no live twin."""

    def __init__(self, path, title, desc, h1, answer, body, crumbs, stamp, live=None, eyebrow="", kind="Checked",
                 hero_cls=""):
        self.path, self.title, self.desc, self.h1, self.answer, self.body = path, title, desc, h1, answer, body
        self.crumbs, self.stamp, self.live, self.eyebrow, self.kind, self.hero_cls = crumbs, stamp, live, eyebrow, kind, hero_cls


NAV = (("/", "Home", "home"), (OFFERS_PATH, "Offers", "list"), ("/this-week/", "This week", "week"),
       (MY_PATH + "#saved", "Saved", "heart"), (MY_PATH + "#cards", "My cards", "card"))


def shell(site, p: V, css_v: str, js_v: str) -> str:
    base = site.base
    canon = base + (p.live if p.live else p.path)
    page = g.Page(p.path, p.title, p.desc, p.h1, p.answer, "", [(n, pth) for n, pth in p.crumbs], p.kind, p.stamp,
                  p.path, noindex=True)
    cur = ' aria-current="page"'
    top = "".join(f'<a href="{vp(h)}"{cur if vp(h) == p.path else ""}>{t}</a>' for h, t in (
        (OFFERS_PATH, "Offers"), ("/this-week/", "This week"), ("/best-card-for-movie-tickets/", "Best card"),
        (CALC_PATH, "Booking check"), (g.GUIDE_PATH, "Guide")))
    bottom = "".join(f'<a href="{vp(h)}"{cur if vp(h.split("#")[0]) == p.path and "#" not in h else ""}>{ico(i)}<span>{t}</span></a>'
                     for h, t, i in NAV)
    crumbs = ""
    if len(p.crumbs) > 1 and p.path != vp("/"):
        crumbs = ('<nav class="cr w" aria-label="Breadcrumb"><ol>' + "".join(
            f'<li><a href="{pth}">{E(n)}</a></li>' if i < len(p.crumbs) - 1 else f'<li aria-current="page">{E(n)}</li>'
            for i, (n, pth) in enumerate(p.crumbs)) + "</ol></nav>")
    live_link = p.live or "/"
    foot = "".join(f'<a href="{h}">{t}</a>' for h, t in (
        (vp(OFFERS_PATH), "All offers"), (vp("/spotted/"), "Spotted leads"), (vp(g.GUIDE_PATH), "How card offers work"),
        ("/how-we-check/", "How we check"), ("/changes/", "Changes"), ("/about/", "About"), ("/corrections/", "Corrections"),
        ("/disclosures/", "Disclosures"), ("/offers.json", "Open data"), ("/agents/", "For agents")))
    return f'''<!doctype html>
<html lang="en-IN" class="v2">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{E(p.title)}</title>
<meta name="description" content="{E(g.meta_desc(p.desc))}">
<link rel="canonical" href="{canon}">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#0B130F">
<meta name="color-scheme" content="dark">
<link rel="icon" href="/assets/brand/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png">
<meta property="og:type" content="website"><meta property="og:site_name" content="FDFS">
<meta property="og:title" content="{E(p.title)}"><meta property="og:description" content="{E(g.meta_desc(p.desc))}">
<meta property="og:url" content="{base}{p.path}">{site.og_meta(page)}
<link rel="preload" href="/assets/fonts/google-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/bricolage-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/v2.css?v={css_v}">
<script>document.documentElement.classList.add('js')</script>
<script type="application/ld+json">{site.jsonld(page)}</script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="hd"><div class="w hd-in"><a class="brand" href="{V2}/" aria-label="FDFS home">{site.mark()}<svg class="wm" viewBox="0 0 {site.ww} {site.wh}" aria-hidden="true"><path d="{site.word}"/></svg></a>
<nav class="hd-nav" aria-label="Main">{top}</nav>{g.HEADER_SEARCH}<button class="mc js" type="button" data-wallet>{ico("card")}<span class="mc-l">My cards</span><span class="mc-n" data-wn></span></button></div></header>
<p class="pv w">You're looking at the new FDFS, a preview. <a href="{live_link}">Open the current site</a></p>
<section class="hero w{p.hero_cls}" aria-labelledby="h1">
{f'<p class="ey">{E(p.eyebrow)}</p>' if p.eyebrow else ""}<h1 id="h1">{p.h1}</h1>
<div class="tk" id="answer"><p class="tk-q"><span class="dot" aria-hidden="true"></span>{p.kind} <time datetime="{g.iso(p.stamp)}" data-stamp>{g.fmt_stamp(p.stamp)}</time></p>
<div class="tk-a">{p.answer}</div></div>
</section>
{crumbs}
<main id="main">
{p.body}
</main>
<footer class="ft"><div class="w">
<p class="ft-tag"><b>FDFS</b> · Film · Deals · Friends · Seats. {E(site.cfg["tagline"])}</p>
<nav class="ft-nav" aria-label="Site">{foot}</nav>
<p class="ft-legal"><strong>{g.FOOTER_LINE}</strong> Offers change: read the terms on the bank's or app's page before you pay. Names of banks and apps only say where an offer applies. Offer data: <a href="/offers.json">CC BY 4.0</a>.</p>
</div></footer>
<nav class="bn" aria-label="Quick links">{bottom}</nav>
<dialog class="sheet" id="wallet" aria-labelledby="wallet-h"><form method="dialog" class="sh-in"><div class="sh-hd"><h2 id="wallet-h">My cards</h2><button class="x" value="close" aria-label="Close">×</button></div>
<p class="sh-p">Pick the cards you hold. We keep only the card's name, on this device. Never a card number.</p><div class="sh-list" data-wl></div>
<div class="sh-ft"><button class="btn" value="close">Done</button></div></form></dialog>
<script src="/assets/search.js?v={g.content_hash(g.HS_JS)[:8]}" defer></script>
<script src="/assets/v2.js?v={js_v}" defer></script>
</body>
</html>
'''


# ---------------------------------------------------------------- pages
def section(sid: str, title: str, inner: str, lead: str = "", cls: str = "") -> str:
    return (f'<section class="sec w{(" " + cls) if cls else ""}" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{title}</h2>'
            + (f'<p class="lead">{lead}</p>' if lead else "") + inner + "</section>")


def tools_bar(with_app: bool = True) -> str:
    chips_ = [("all", "All"), ("mine", "Fits my cards"), ("saved", "Saved"), ("bogo", "2nd ticket free"),
              ("pct", "% off"), ("nospend", "No spend rule"), ("events", "Live events")]
    apps = [("", "All apps"), ("bms", "BookMyShow"), ("district", "District")]
    return ('<div class="tb js" data-tools><label class="sr" for="q">Search checked offers</label>'
            '<div class="tb-s"><input id="q" type="search" autocomplete="off" enterkeyhint="search" maxlength="60" '
            'aria-describedby="q-d"><span class="tb-h" id="q-d">Search a bank, card or app</span></div>'
            '<div class="tb-r"><div class="cp" role="group" aria-label="Filter">'
            + "".join(f'<button type="button" data-f="{k}" aria-pressed="{"true" if k == "all" else "false"}">{t}</button>' for k, t in chips_)
            + "</div>"
            + ('<div class="tb-x"><label for="app">App</label><select id="app">'
               + "".join(f'<option value="{k}">{t}</option>' for k, t in apps) + "</select>" if with_app else '<div class="tb-x">')
            + '<label for="sort">Sort</label><select id="sort"><option value="cap">Highest cap</option>'
              '<option value="end">Ends first</option><option value="checked">Checked most recently</option>'
              '<option value="bank">Bank A to Z</option></select></div></div>'
            '<p class="tb-n" aria-live="polite" data-count></p></div>')


def answer_best(site, offers: list, today: date) -> str:
    movie = [o for o in order(offers) if o.is_movie and usable_on(o, today)]
    day = today.strftime("%a %-d %b")
    if not movie:
        return f"<p class=\"tk-w\">No checked movie offer works on {day}.</p>"
    b = movie[0]
    return (f'<p class="tk-l">Best checked offer, booking on {day}</p><p class="tk-v" data-best><a href="{vp(g.offer_path(b.id))}">'
            f'{E(g.what(b))} <span>{E(g.cap(b))}</span></a></p><p class="tk-w" data-best-w>{E(who_nice(b))} · {E(plain_app(b))}. '
            f'{E(kc(b, today))}.</p>')


def collections(site, offers: list) -> str:
    movie = [o for o in order(offers) if o.is_movie]
    sets = [("bogo", "Two tickets, one bill", "The second ticket is free, up to the cap.", [o for o in movie if o.kind == "bogo"]),
            ("anyday", "Any day of the week", "No day rule in the terms.", [o for o in movie if "any" in o.days]),
            ("nospend", "No spend rule", "No minimum card spend before the offer works.", [o for o in movie if not g.spend_gate(o.quota_note)])]
    cards = []
    for k, t, s, xs in sets:
        if not xs:
            continue
        top = "".join(f'<li><a href="{vp(g.offer_path(o.id))}">{E(who_nice(o))}</a> <span>{E(g.cap(o))}</span></li>' for o in xs[:3])
        cards.append(f'<article class="co co-{k}"><h3>{E(t)}</h3><p>{E(s)}</p><ul>{top}</ul>'
                     f'<a class="co-a" href="{vp(OFFERS_PATH)}?f={k}">See all {len(xs)}</a></article>')
    return f'<div class="cos">{"".join(cards)}</div>' if cards else ""


def apps_tiles(site, offers: list) -> str:
    tiles = []
    for k in g.APPS:
        n = [o for o in offers if g.app_key(o.platform) == k]
        if not n:
            continue
        movie = sum(1 for o in n if o.is_movie)
        best = max((free_cap(o) for o in n if o.is_movie), default=0)
        tiles.append(f'<a class="ap" href="{vp(g.hub_path(k))}"><span class="ap-n">{E(g.APPS[k][1])}</span>'
                     f'<span class="ap-c">{movie} checked movie offer{"s" if movie != 1 else ""}</span>'
                     + (f'<span class="ap-b">Highest cap ₹{best:,}</span>' if best else "") + "</a>")
    return f'<div class="aps">{"".join(tiles)}</div>'


HOME_FAQ = [
    ("Is FDFS a booking site?", "<p>No. We read the bank's and the app's own terms and list the offers that pass our checks. "
                                "You book on the app as usual and pay with the card the offer names.</p>"),
    ("Do you need my card number?", "<p>Never. My cards keeps only the card's name, like \"HSBC Premier credit card\", in "
                                    "this browser. Nothing is sent to us.</p>"),
    ("Why did an offer not work at checkout?", "<p>The usual reasons are in the terms: the monthly limit is used up, the card "
                                               "isn't one of the listed variants, a spend rule isn't met, or a quota ran out. Each offer page lists them.</p>"),
    ("How often do you check?", f'<p>Every day. Each offer shows the minute we last checked it, and anything we couldn\'t '
                                f'recheck within 7 days comes off the list. <a href="/how-we-check/">How we check</a>.</p>'),
    ("What are spotted leads?", f'<p>Offers we saw on the web but haven\'t checked against the terms yet. They look different on '
                                f'purpose and we never count them as checked. <a href="{vp("/spotted/")}">See the leads</a>.</p>'),
]


def page_home(site, offers, spots, now, today, live) -> V:
    lp = live.get("/")
    movie = [o for o in offers if o.is_movie]
    banks = sorted({site.bank_name(o.issuer) for o in offers if o.is_bank})
    body = (
        f'<section class="sec w wkb" id="week" aria-labelledby="week-h"><h2 id="week-h">Your week at the movies</h2>'
        f'<p class="lead"><span data-wk-lead>The best checked offer for each day. Add your cards to see only yours.</span></p>'
        f'{week_strip(offers, today)}<p class="more"><a href="{vp("/this-week/")}">Plan the week</a></p></section>'
        + section("where", "Where do you book?", apps_tiles(site, offers))
        + section("offers", "Offers that pass our checks", tools_bar() + offer_list(site, order(offers), today, lid="list"),
                  lead=f"{len(movie)} checked movie offer{'s' if len(movie) != 1 else ''} from {jand(banks)}. "
                       "Each one is read against the official terms.")
        + section("moods", "Pick your kind of deal", collections(site, offers))
        + section("calc", "Which offer works for your booking?",
                  f'<p class="cta-p">Pick the day, the app and how many tickets. We list the checked offers whose terms allow it, highest cap first.</p>'
                  f'<a class="btn" href="{vp(CALC_PATH)}">Check my booking</a>', cls="cta")
        + section("leads", "Leads we haven't checked yet",
                  f'<p class="cta-p">Offers seen on the web whose terms we haven\'t read yet. Open the source before you rely on one.</p>'
                  f'<a class="btn btn-q" href="{vp("/spotted/")}">See the spotted leads</a>', cls="cta cta-q") if spots else ""
    ) + section("faq", "Questions people ask", faq(HOME_FAQ))
    return V(vp("/"), lp.title if lp else "Movie ticket offers · FDFS", lp.desc if lp else site.cfg["tagline"],
             lp.h1 if lp else "Movie ticket offers, checked at the source.",
             answer_best(site, offers, today), body, [("FDFS", "/"), ("New design", vp("/"))], now, live="/",
             eyebrow="Film · Deals · Friends · Seats", hero_cls=" hero-home")


def page_offers(site, offers, now, today) -> V:
    banks = sorted({site.bank_name(o.issuer) for o in offers if o.is_bank})
    body = section("all", "Every checked offer", tools_bar() + offer_list(site, order(offers), today, lid="list"),
                   lead="Filter by your cards, the app, the kind of deal, or search. Sorted by the highest cap first.")
    n = len(offers)
    return V(vp(OFFERS_PATH), "All checked movie ticket offers · FDFS",
             f"Every movie and live-event ticket offer that passes FDFS's checks: {n} from {jand(banks)}, with caps, days and limits.",
             "All checked offers", f"<p class=\"tk-l\">{n} checked offer{'s' if n != 1 else ''}</p><p class=\"tk-w\">From {E(jand(banks))}. "
             "Each one links to the official terms.</p>", body, [("Offers", vp("/")), ("All offers", vp(OFFERS_PATH))], now)


def relink(html_: str, v2paths: set) -> str:
    def f(m):
        h = m.group(1)
        path = h.split("#")[0]
        return f'href="{vp(h)}"' if path in v2paths else m.group(0)
    return re.sub(r'href="(/[^"]*)"', f, html_)


def list_page(site, live, path, offers, now, today, v2paths, crumb, extra="") -> V | None:
    lp = live.get(path)
    if not lp:
        return None
    body = section("list-s", "The checked offers", tools_bar(with_app=app_count(offers) > 1) + offer_list(site, order(offers), today, lid="list")) + extra
    crumbs = [("Offers", vp("/"))] + [(n, vp(p_)) for n, p_ in lp.crumbs[1:]] if len(lp.crumbs) > 1 else [("Offers", vp("/")), (crumb, vp(path))]
    return V(vp(path), lp.title, lp.desc, lp.h1, relink(lp.answer, v2paths), body, crumbs, lp.stamp, live=path,
             kind=lp.stamp_kind)


def app_count(offers) -> int:
    return len({app_k(o) for o in offers})


def page_offer(site, o, live, today, v2paths, offers) -> V:
    lp = live.get(g.offer_path(o.id))
    url = site.base + g.offer_path(o.id)
    text = (f"Movie plan: {g.what(o)} ({g.cap(o)}) with {who_nice(o)} on {plain_app(o)}. "
            f"{kc(o, today)}. Checked {g.fmt_dm(o.checked_at.astimezone(g.IST).date())}:")
    wa = "https://wa.me/?text=" + g.quote_url(f"{text} {url}")
    used = (f'<div class="use js" data-use="{E(o.id)}" data-max="{o.monthly_limit}"><p class="use-t">This month: '
            f'<b data-use-n>0</b> of {o.monthly_limit} used</p><button class="btn btn-s" type="button" data-use-add>I used it</button>'
            f'<button class="lnk" type="button" data-use-undo>Undo</button></div>') if o.monthly_limit else ""
    acts = (f'<div class="acts" role="group" aria-label="Save or share">'
            f'<button class="btn js" type="button" data-save="{E(o.id)}" aria-pressed="false">{ico("heart")}<span data-save-l>Save</span></button>'
            f'{g.ext(wa, "Plan on WhatsApp", cls="btn btn-g")}'
            f'<button class="btn btn-g js" type="button" data-copy="{E(url)}">Copy link</button>'
            + (f'<button class="btn btn-g js" type="button" data-ics data-to="{o.valid_to.isoformat()}" data-title="{E("Last day: " + who_nice(o) + ", " + g.what(o) + " " + g.cap(o))}" data-url="{E(url)}">Add the last day to my calendar</button>' if o.valid_to else "")
            + "</div>")
    others = [x for x in order(offers) if x.id != o.id and app_k(x) == app_k(o) and x.is_movie == o.is_movie][:3]
    body = (f'<section class="sec w" id="plan" aria-labelledby="plan-h"><h2 id="plan-h">Use it</h2>{acts}{used}'
            f'<p class="fit-o js" data-fit="{E(o.id)}" hidden></p>'
            f'<p class="note">Saved offers stay on this device. If one ends or its terms change, My cards tells you next time you open FDFS.</p></section>'
            + section("terms", "Every term, from the official page", g.receipt(site, o, today, []))
            + section("quotes", "What the terms say, word for word", g.quotes_html(o))
            + (section("more", f"Other checked offers on {E(g.app_name(o))}", offer_list(site, others, today)) if others else ""))
    h1 = lp.h1 if lp else f"{E(who_nice(o))}: {E(g.what(o))}"
    ans = (f'<p class="tk-v">{E(g.what(o))} <span>{E(g.cap(o))}</span></p><p class="tk-w">{E(who_nice(o))} · {E(g.where(o))}. '
           f'{E(kc(o, today))}.</p>')
    crumbs = [("Offers", vp("/")), ("All offers", vp(OFFERS_PATH)), (who_nice(o), vp(g.offer_path(o.id)))]
    return V(vp(g.offer_path(o.id)), lp.title if lp else f"{who_nice(o)} · FDFS", lp.desc if lp else g.what_full(o), h1, ans,
             body, crumbs, o.checked_at, live=g.offer_path(o.id) if lp else None)


def week_rows(xs: list, today: date) -> str:
    """One line per offer on each day. Full cards for 7 days repeat each offer up to 7 times (34 offers made the page
    30 KB gzip); the offer's own page has the card. The script hides lines that don't fit the visitor's cards."""
    li = "".join(f'<li data-id="{E(o.id)}"><a href="{vp(g.offer_path(o.id))}">{E(who_nice(o))}</a> on {E(g.app_name(o))}: '
                 f'<b>{E(g.what(o))} {E(g.cap(o))}</b>. {E(kc(o, today))}.</li>' for o in xs)
    return f'<ul class="wl wr">{li}</ul><p class="empty" data-day-none hidden>None of your cards has a checked offer this day.</p>'


def page_week(site, offers, now, today, live) -> V:
    lp = live.get("/this-week/")
    days = []
    for i in range(7):
        d = today + timedelta(days=i)
        xs = sorted([o for o in offers if usable_on(o, d)], key=lambda o: (-free_cap(o), o.id))
        lab = d.strftime("%A %-d %b")
        days.append(f'<section class="day" id="d-{d.isoformat()}" data-date="{d.isoformat()}" aria-labelledby="d-{d.isoformat()}-h">'
                    f'<h3 id="d-{d.isoformat()}-h">{E(lab)}</h3>' + (week_rows(xs, today) if xs else
                    '<p class="empty">No checked movie offer for this day.</p>') + "</section>")
    sat = next((today + timedelta(days=i) for i in range(7) if (today + timedelta(days=i)).weekday() == 5), today)
    wk = [o for o in order(offers) if usable_on(o, sat) or usable_on(o, sat + timedelta(days=1))]
    weekend = "".join(f'<li><a href="{vp(g.offer_path(o.id))}">{E(who_nice(o))}</a>: {E(g.what(o))} {E(g.cap(o))}, {E(g.day_rule(o, today)[1])}</li>' for o in wk[:5])
    body = (section("weekend", "This weekend", f'<ul class="wl">{weekend}</ul>' if weekend else '<p class="empty">No checked offer this weekend.</p>',
                    lead=f"Saturday {sat.day} and Sunday {(sat + timedelta(days=1)).day} {sat.strftime('%b')}.")
            + section("days", "Day by day", '<p class="lead"><span data-wk-lead>Every checked movie offer you can use on each day, highest cap first.</span></p>'
                      + "".join(days)))
    return V(vp("/this-week/"), "This week's movie ticket offers, day by day · FDFS",
             "Which checked movie ticket offer to use on each day of the next week, highest cap first, with the weekend at the top.",
             "Your week at the movies", answer_best(site, offers, today), body,
             [("Offers", vp("/")), ("This week", vp("/this-week/"))], now, live="/this-week/" if lp else None)


def checker_rows(offers: list, n: int, day: date) -> list:
    return [o for o in order(offers) if o.is_movie and usable_on(o, day) and n >= need(o)]


def checker_line(o, today: date) -> str:
    extra = [x for x in (g.day_rule(o, today)[1] if o.days and "any" not in o.days else "",
                         g.spend_gate(o.quota_note) or "", g.times(o.monthly_limit) if o.monthly_limit else "") if x]
    return (f'<li><a href="{vp(g.offer_path(o.id))}">{E(who_nice(o))}</a> on {E(g.app_name(o))}: <b>{E(g.what(o))} {E(g.cap(o))}</b>'
            + (f'. {E(". ".join(extra))}' if extra else "") + "</li>")


def page_calc(site, offers, now, today) -> V:
    """Which checked offers a booking qualifies for, from the terms (day, app, tickets, cards, spend rule). Decisions 139
    and P3 stand: no ticket price, no estimate of what anyone pays or keeps. The cap shown is the terms' own."""
    rows = checker_rows(offers, 2, today)
    days = "".join(f'<option value="{(today + timedelta(days=i)).isoformat()}">{(today + timedelta(days=i)).strftime("%a %-d %b")}</option>'
                   for i in range(7))
    form = ('<form class="calc js" data-calc onsubmit="return false"><div class="calc-g">'
            f'<label>Day you book<select name="day">{days}</select></label>'
            '<label>Tickets in one booking<select name="n">' + "".join(
                f'<option value="{i}"{" selected" if i == 2 else ""}>{i}</option>' for i in range(1, 7)) + '</select></label>'
            '<label>App<select name="app"><option value="">Any app</option>' + "".join(
                f'<option value="{k}">{E(g.APPS[k][1])}</option>' for k in g.APPS if any(g.app_key(o.platform) == k for o in offers))
            + '</select></label></div>'
            '<label class="ck"><input type="checkbox" name="mine"> Only my cards</label>'
            '<label class="ck"><input type="checkbox" name="nospend"> Hide offers that need earlier card spend</label></form>')
    out = "".join(checker_line(o, today) for o in rows) or '<li>No checked offer fits this booking.</li>'
    body = section("calc-s", "Your booking", form + f'<ol class="cr-l" data-calc-out>{out}</ol>'
                   '<p class="note">From the terms we checked. The cap is the most the bank takes off; the app works out the '
                   'real amount at checkout. Monthly limits you\'ve already used aren\'t counted.</p>',
                   lead=f"Shown for 2 tickets booked on {today.strftime('%a %-d %b')}. Change the booking to see what fits.")
    return V(vp(CALC_PATH), "Which movie ticket offer works for my booking? · FDFS",
             "Pick the day, the app and how many tickets: FDFS lists the checked card offers whose terms allow that booking, highest cap first.",
             "Which offer works for your booking?", '<p class="tk-l">From the checked terms</p><p class="tk-w">Day, app, tickets '
             'and your cards. We list every checked offer that allows it.</p>', body,
             [("Offers", vp("/")), ("Booking check", vp(CALC_PATH))], now)


def page_my(site, now) -> V:
    body = (
        section("cards", "My cards", '<div class="my-cards" data-my-cards><p class="empty">No cards added yet.</p></div>'
                '<button class="btn js" type="button" data-wallet>Add or remove cards</button>',
                lead="The offers that fit them are marked across FDFS. Kept in this browser only.")
        + section("saved", "Saved offers", '<div data-saved><p class="empty">Nothing saved yet. Tap the heart on an offer.</p></div>',
                  lead="If a saved offer ends or its cap, days or dates change, it's flagged here.")
        + section("used", "Used this month", '<div data-used><p class="empty">Mark an offer as used on its page and it shows here. '
                  'Counts reset on the 1st.</p></div>', lead="Most card offers work once or twice a month. Keep count here.")
        + section("diary", "Movie diary", '<form class="diary js" data-diary onsubmit="return false"><div class="calc-g">'
                  '<label>Date<input name="date" type="date" required></label><label>Movie<input name="movie" maxlength="60" required></label>'
                  '<label>Paid (₹)<input name="paid" type="number" inputmode="numeric" min="0" max="100000" required></label>'
                  '<label>Off with the offer (₹)<input name="off" type="number" inputmode="numeric" min="0" max="100000"></label></div>'
                  '<button class="btn" type="submit">Add to my diary</button></form><div data-diary-list></div>',
                  lead="Your own log of what you watched and what you paid. Only you see it.")
        + '<noscript><p class="w empty">This page keeps your cards, saved offers and diary in your browser, so it needs JavaScript.</p></noscript>'
        + section("data", "Your data", '<p class="cta-p">Everything on this page stays in this browser. Clearing it removes your cards, '
                  'saved offers, counts and diary from this device.</p><button class="btn btn-g js" type="button" data-clear>Clear everything</button>'))
    return V(vp(MY_PATH), "My cards, saved offers and diary · FDFS",
             "Your cards, saved movie ticket offers, monthly use and movie diary on FDFS, kept only in this browser.",
             "My cards", '<p class="tk-l">Kept on this device</p><p class="tk-w" data-my-sum>Add your cards and FDFS shows the offers they get.</p>',
             body, [("Offers", vp("/")), ("My cards", vp(MY_PATH))], now)


def spot_card(sp) -> str:
    plat = g.SPOT_PLATFORM.get(sp.platform, sp.platform.title() if sp.platform else "")
    link = (g.ext(g.PVR_HOME, "pvrcinemas.com" + g.icon("out"), cls="tl", sr="PVR INOX home page") if sp.is_pvr
            else g.ext(sp.source_url, "Source" + g.icon("out"), cls="tl", sr=E(sp.source_name)))
    when = g.fmt_day(sp.spotted_at.astimezone(g.IST).date())
    bid = sp.bank if sp.bank != "none" else g.bank_id(sp.issuer)
    code = f'<p class="sp-c">Code in the source: <code>{E(sp.code)}</code> (not checked)</p>' if sp.code else ""
    return (f'<article class="sp" data-spotted="{sp.spotted_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'data-end="{sp.valid_to.isoformat() if sp.valid_to else ""}" data-bank="{E(bid)}">'
            f'<div class="oc-top">{g.monogram(bid, sp.issuer)}<div class="oc-id"><p class="oc-who">{E(sp.issuer)}</p>'
            f'<p class="oc-app">{E(plat)}</p></div><span class="sp-pill">Not checked</span></div>'
            f'<h3 class="sp-h">{E(sp.headline)}</h3>{code}'
            f'<p class="oc-ft"><span>Seen on {E(sp.source_name)} · {E(when)}</span>{link}</p></article>')


def page_spotted(site, spots, now, live) -> V | None:
    lp = live.get("/spotted/")
    if not lp:
        return None
    body = section("sp-l", "Spotted, not checked", '<div class="ol">' + "".join(spot_card(s) for s in spots) + "</div>",
                   lead=E(g.SPOT_INTRO) + " A lead drops off 7 days after we saw it, or on the end date its source gives.")
    return V(vp("/spotted/"), lp.title, lp.desc, lp.h1, '<p class="tk-l">Not checked against the terms</p><p class="tk-w">'
             'Each lead links to where we saw it. We list an offer as checked only once its terms pass.</p>', body,
             [("Offers", vp("/")), ("Spotted", vp("/spotted/"))], now, live="/spotted/", kind="Updated")


def page_guide(site, offers, live, v2paths) -> V | None:
    lp = live.get(g.GUIDE_PATH)
    secs = g.guide_sections(site, offers)
    if not lp or not secs:
        return None
    toc = '<ol class="toc">' + "".join(f'<li><a href="#{sid}">{E(q)}</a></li>' for sid, q, _ in secs) + "</ol>"
    body = (f'<section class="sec w" aria-labelledby="toc-h"><h2 id="toc-h">In this guide</h2>{toc}</section>'
            + "".join(f'<section class="sec w gd" id="{sid}" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{E(q)}</h2>{relink(a, v2paths)}</section>'
                      for sid, q, a in secs))
    return V(vp(g.GUIDE_PATH), lp.title, lp.desc, lp.h1, relink(lp.answer, v2paths), body,
             [("Offers", vp("/")), ("Guide", vp(g.GUIDE_PATH))], lp.stamp, live=g.GUIDE_PATH, kind=lp.stamp_kind)


# ---------------------------------------------------------------- build
def asset(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def css_text() -> str:
    return asset("v2.css")


def js_text() -> str:
    return asset("v2.js")


def build_v2(site, pages: list, offers: list, spots: list, now: datetime, out: Path, host: str) -> list:
    """Write the v2 preview into out/v2/ and its two assets. Returns the v2 paths written. Touches nothing else."""
    today = now.astimezone(g.IST).date()
    live = {p.path: p for p in pages}
    cards = g.card_products(offers)
    banks = sorted({o.slug for o in offers if o.is_bank})
    apps = [k for k in g.APPS if any(g.app_key(o.platform) == k for o in offers)]
    wsets = g.weekday_sets(offers)
    planned = (["/", OFFERS_PATH, "/this-week/", CALC_PATH, MY_PATH, "/spotted/", g.GUIDE_PATH, "/best-card-for-movie-tickets/"]
               + [f"/bank/{s}/" for s in banks] + [g.hub_path(k) for k in apps] + [f"/card/{s}/" for s in cards]
               + [g.day_path(k) for k in wsets] + [g.offer_path(o.id) for o in offers])
    v2paths = {p for p in planned if p in live or p in ("/", OFFERS_PATH, CALC_PATH, MY_PATH, "/this-week/")}
    vs = [page_home(site, offers, spots, now, today, live), page_offers(site, offers, now, today),
          page_week(site, offers, now, today, live), page_calc(site, offers, now, today), page_my(site, now)]
    for s in banks:
        vs.append(list_page(site, live, f"/bank/{s}/", [o for o in offers if o.is_bank and o.slug == s], now, today, v2paths, s))
    for k in apps:
        vs.append(list_page(site, live, g.hub_path(k), [o for o in offers if g.app_key(o.platform) == k], now, today, v2paths, g.APPS[k][1]))
    for s, c in sorted(cards.items()):
        vs.append(list_page(site, live, f"/card/{s}/", c["offers"], now, today, v2paths, c["name"]))
    for k in sorted(wsets, key=g.DAY_IDX.get):
        named = [o for o in offers if o.is_movie and (k in g.day_keys(o) or "any" in o.days)]
        vs.append(list_page(site, live, g.day_path(k), named, now, today, v2paths, g.DAY[k]))
    ny = site.cfg.get("not_yet_listed") or []
    vs.append(list_page(site, live, "/best-card-for-movie-tickets/", [o for o in offers if o.is_movie], now, today, v2paths, "Best card",
                        extra=section("ny", "Not on this list yet", f'<p class="cta-p">{E(jand(ny))}: none of their offers has passed '
                                      'our checks yet. We add a card only once its terms do.</p>', cls="cta") if ny else ""))
    vs.append(page_spotted(site, spots, now, live))
    vs.append(page_guide(site, offers, live, v2paths))
    vs += [page_offer(site, o, live, today, v2paths, offers) for o in sorted(offers, key=lambda x: x.id)]
    css, js = css_text(), js_text()
    css_v, js_v = g.content_hash(css)[:8], g.content_hash(js)[:8]
    written = []
    for p in [x for x in vs if x]:
        p.body = relink(p.body, v2paths) if p.path != vp("/") else relink(p.body, v2paths)
        html_text = shell(site, p, css_v, js_v)
        g.check_links(html_text, p.path, host)
        bad = g.BANNED.search(re.sub(r'<script type="application/ld\+json">.*?</script>', "", html_text))
        if bad:
            raise SystemExit(f"banned wording on {p.path}: {bad.group(0)!r}")
        target = out / p.path.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
        written.append(p.path)
    data = {"generated": now.isoformat(timespec="seconds"), "today": today.isoformat(),
            "offers": [row(site, o, today) for o in order(offers)], "cards": wallet_cards(site, offers),
            "banks": {g.bank_id(o.issuer): site.bank_name(o.issuer) for o in offers if o.is_bank}}
    (out / "v2" / "data.json").write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                                          encoding="utf-8")
    (out / "assets" / "v2.css").write_text(css, encoding="utf-8")
    (out / "assets" / "v2.js").write_text(js, encoding="utf-8")
    return written


def gz(s: str) -> int:
    return len(gzip.compress(s.encode("utf-8")))


def jand(xs) -> str:
    xs = list(xs)
    return g.join_and(xs) if xs else "no bank yet"


def kc(o, today: date) -> str:
    return g.key_condition(o, today).rstrip(".")
