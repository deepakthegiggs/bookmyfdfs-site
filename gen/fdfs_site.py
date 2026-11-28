"""FDFS static site generator (S1, decision 111).

Input:  data/offers.json   - the Offer Watchdog's verified-only export (090, export_offers_json)
        data/history/*.json - dated snapshots of that export, for the changelog
        data/site.json      - site config (no product or chat-app links before launch)
        data/build-state.json - per-URL content hash + lastmod (sitemap honesty)
Output: dist/

Rules this file enforces (and tests/test_generator.py checks):
- Deterministic: the only clock is the export's generated_at. Same inputs + same state = same bytes.
- Defence in depth: an offer is shown as valid only if terms_verified, started, not expired and
  checked within STALE_DAYS of the build time, whatever the export says.
- No page without data: bank pages only for banks with >= 1 shown offer; the comparison only with
  >= 1 shown movie offer; no per-city pages (New this week is one noindex stub).
- Every page: answer box first, a visible "Checked/Updated <date time> IST" that equals JSON-LD
  dateModified, Organization + WebSite + BreadcrumbList, canonical, branded title, the footer line.
- sitemap lastmod moves only when a page's content (not its check stamp) changes.
Python 3.9+, stdlib only.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prelaunch as PRELAUNCH  # noqa: E402  pre-launch ban list (encoded)
import plan_pages as PLAN  # noqa: E402  P3: saved, sort, /calendar/, checklist (decisions 150-157)
import v2_site as V2  # noqa: E402  decision 171: the site v2 preview under /v2/ (noindex, out of every feed)
IST = timezone(timedelta(hours=5, minutes=30))
PLAN.g = sys.modules[__name__]
V2.g = sys.modules[__name__]
STALE_DAYS = 7
E = html.escape
FOOTER_LINE = "Independent. Not affiliated with BookMyShow, District, any cinema or any bank."
BANNED = re.compile(r"you save|save ₹|hurry|only \d+ left|last chance|ends soon|limited time|don.t miss|act now|"
                    r"\bbot\b|" + PRELAUNCH.PATTERN, re.I)   # the pre-launch product ban list, encoded in gen/prelaunch.py

PLATFORM = {"bms": "BookMyShow", "district": "District"}
DAY = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
       "sat": "Saturday", "sun": "Sunday"}
DAY_IDX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
# Plain-words for 090's condition codes. Unknown codes are reported (build warnings), never guessed.
CONDITIONS = {
    "full_payment_on_card": "Pay the full amount with the card",
    "no_wallet": "Not with wallet payments",
    "overdue_cards_excluded": "Not for cards with overdue payments",
    "lowest_priced_ticket": "The discount applies to the lowest-priced ticket",
    "booking_fee_on_full_price": "The booking fee is charged on the full ticket price",
    "new_card_spend_waiver": "New cards: no minimum spend in the month of issue and the next 3 months",
}
KIND_GROUP = {"bogo": "Second ticket free or off", "pct": "Percentage off", "flat": "Flat amount off",
              "cashback": "Cashback", "points": "Reward points", "complimentary": "Free tickets"}
PERIOD_WORDS = {"month": "a month", "quarter": "a quarter", "year": "a year"}   # kind complimentary (engine, 27 Nov)

# One bank vocabulary for both tiers, the search box and the "My cards" wallet (redesign r1).
# (id, display name, monogram, issuer pattern, search aliases). Names are plain text only: no logos, no bank colours.
BANKS = (
    ("hdfc", "HDFC Bank", "HD", r"\bhdfc", ("hdfc",)),
    ("sbi", "SBI Card", "SBI", r"\bsbi ?cards?\b|\bsbicard\b", ("sbi", "sbi card", "sbicard")),   # not State Bank of India
    ("icici", "ICICI Bank", "IC", r"\bicici", ("icici",)),
    ("axis", "Axis Bank", "AX", r"\baxis", ("axis",)),
    ("kotak", "Kotak", "KO", r"\bkotak", ("kotak", "kotak mahindra")),
    ("hsbc", "HSBC", "HS", r"\bhsbc", ("hsbc",)),
    ("indusind", "IndusInd", "IIB", r"\bindusind", ("indusind", "indus")),
    ("idfc", "IDFC FIRST", "ID", r"\bidfc", ("idfc", "idfc first", "idfcfirst")),
    ("rbl", "RBL Bank", "RBL", r"\brbl\b", ("rbl",)),
    ("yes", "YES Bank", "YES", r"^yes\b", ("yes bank", "yesbank", "yes")),
    ("au", "AU Bank", "AU", r"^au\b|\bau small", ("au", "au bank", "au small finance")),
    ("bob", "BOBCARD", "BOB", r"bobcard|bank of baroda|\bbob\b", ("bob", "bobcard", "baroda", "bank of baroda")),
    ("sc", "Standard Chartered", "SC", r"standard chartered|stanchart", ("sc", "stanchart", "standard chartered")),
    ("dbs", "DBS Bank", "DBS", r"\bdbs\b", ("dbs",)),
    ("federal", "Federal Bank", "FB", r"\bfederal\b", ("federal",)),
    ("amex", "American Express", "AE", r"american express|\bamex\b", ("amex", "american express")),
    ("boi", "Bank of India", "BOI", r"^bank of india", ("boi", "bank of india")),
    ("union", "Union Bank", "UBI", r"^union bank", ("union", "union bank", "union bank of india", "ubi")),
    ("canara", "Canara Bank", "CB", r"\bcanara", ("canara",)),
    ("indianbank", "Indian Bank", "IB", r"^indian bank", ("indian bank",)),
    ("cub", "City Union Bank", "CUB", r"city union", ("cub", "city union")),
    ("pnb", "PNB", "PNB", r"punjab national|\bpnb\b", ("pnb", "punjab national")),
    ("onecard", "OneCard", "1C", r"\bone ?card\b", ("onecard", "one card")),
)


def bank_id(issuer: str) -> str:
    """The shared bank key: 'HDFC Bank', 'HDFC' and 'hdfc bank ltd' are all 'hdfc'. Unknown issuers keep issuer_key()."""
    s = re.sub(r"<[^>]+>", " ", issuer or "").strip().lower()
    for bid, _, _, pat, _ in BANKS:
        if re.search(pat, s):
            return bid
    return issuer_key(s)


def bank_label(bid: str, fallback: str) -> str:
    return next((n for b, n, *_ in BANKS if b == bid), fallback)


def monogram(bid: str, issuer: str) -> str:
    """2-3 letter tile, tinted from our own palette by a stable hash (never the bank's colours)."""
    ini = next((m for b, _, m, *_ in BANKS if b == bid), None)
    if not ini:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", re.sub(r"<[^>]+>", " ", issuer)) if w.lower() not in ("bank", "card", "the")]
        ini = (words[0][:2] if len(words) == 1 else "".join(w[0] for w in words[:2])).upper() if words else "?"
    tint = sum(map(ord, bid)) % 5
    return f'<span class="mono mt{tint}" aria-hidden="true">{E(ini)}</span>'


# ---------------------------------------------------------------- data
@dataclass
class Offer:
    raw: dict
    id: str
    issuer: str
    category: str
    kind: str
    platform: str
    channel: str | None
    instrument: str | None
    variants: list
    variants_scope: str | None
    value: dict
    cap_text: str
    days: list
    day_basis: str | None
    show_days: list
    min_tickets: int | None
    monthly_limit: int | None
    quota_note: str | None
    requires_purchase: bool | None
    cities: list
    code: str | None
    conditions: list
    excludes: list
    valid_from: date | None
    valid_to: date | None
    checked_at: datetime | None
    state: str
    source_url: str
    terms_urls: list
    quotes: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.issuer.lower()).strip("-")

    @property
    def is_bank(self) -> bool:
        return self.instrument in ("credit", "debit")

    @property
    def is_movie(self) -> bool:
        return self.category != "events"


def _d(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=IST)


def norm(r: dict) -> Offer:
    """Tolerant read of one export record: 090 is still moving, so every field has a default."""
    g = r.get
    return Offer(raw=r, id=str(g("id") or ""), issuer=str(g("issuer") or "").strip(), category=g("category") or "",
                 kind=g("kind") or "", platform=g("platform") or "", channel=g("channel"),
                 instrument=g("instrument"), variants=[clean_variant(g("issuer") or "", v) for v in (g("card_variants") or [])],
                 variants_scope=g("variants_scope"), value=dict(g("value") or {}), cap_text=g("cap_text") or "",
                 days=list(g("days") or []), day_basis=g("day_basis"), show_days=list(g("show_days") or []),
                 min_tickets=g("min_tickets"), monthly_limit=g("monthly_limit"), quota_note=g("quota_note"),
                 requires_purchase=g("requires_purchase"), cities=list(g("cities") or []), code=g("code"),
                 conditions=list(g("conditions") or []), excludes=list(g("excludes") or []),
                 valid_from=_d(g("valid_from")), valid_to=_d(g("valid_to")), checked_at=_dt(g("checked_at")),
                 state=g("state") or "", source_url=g("source_url") or "",
                 terms_urls=list(g("terms_urls") or ([g("source_url")] if g("source_url") else [])),
                 quotes=dict(g("quotes") or {}))


def shown(o: Offer, now: datetime) -> tuple[bool, str]:
    """Second guard on top of 090's publishable(): never trust the feed alone."""
    today = now.astimezone(IST).date()
    if o.state != "terms_verified":
        return False, f"state {o.state or 'missing'}"
    if not (o.id and o.issuer and o.kind and o.platform and o.source_url):
        return False, "missing id/issuer/kind/platform/source"
    if not o.cap_text and not o.value:
        return False, "no value"
    if o.checked_at is None:
        return False, "never checked"
    if now - o.checked_at > timedelta(days=STALE_DAYS):
        return False, "stale"
    if o.valid_to and o.valid_to < today:
        return False, "expired"
    if o.valid_from and o.valid_from > today:
        return False, "not started"
    if not o.source_url.startswith("https://"):
        return False, "source not https"
    return True, ""


def load(path: Path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    now = _dt(data.get("generated_at"))
    if now is None:
        raise SystemExit("offers.json has no generated_at: refusing to guess the time")
    offers = [norm(r) for r in data.get("offers") or []]
    return now, offers


# ---------------------------------------------------------------- words
def fmt_day(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def fmt_dm(d: date) -> str:
    return f"{d.day} {d:%b}"


def fmt_stamp(t: datetime) -> str:
    t = t.astimezone(IST)
    return f"{t.day} {t:%b %Y}, {t:%H:%M} IST"


def iso(t: datetime) -> str:
    return t.astimezone(IST).isoformat(timespec="seconds")


def clean_variant(issuer: str, v: str) -> str:
    """'FIRST Classic' under issuer 'IDFC FIRST' reads 'Classic': drop words the issuer name already ends with
    (26 Nov: labels read 'IDFC FIRST FIRST Classic'). Display only; the published data keeps the terms' words."""
    iw, vw = issuer.split(), v.split()
    for n in range(min(len(iw), len(vw) - 1), 0, -1):
        if [w.lower() for w in iw[-n:]] == [w.lower() for w in vw[:n]]:
            return " ".join(vw[n:])
    return v


def who(o: Offer) -> str:
    """The card or pass, never wider than the terms: an unstated scope is always 'Select …'."""
    if o.category == "membership":
        return o.issuer if "pass" in o.issuer.lower() else f"{o.issuer} Pass"
    kind = "credit cards" if o.instrument == "credit" else "cards"
    if o.variants_scope == "unstated":
        return f"Select {o.issuer} {kind}"
    if o.variants:
        net = f" {o.raw.get('network')}" if o.raw.get("network") and o.raw["network"].lower() not in " ".join(o.variants).lower() else ""
        vs = [clean_variant(o.issuer, v) for v in o.variants]
        # a debit card says so when its variant name doesn't: "Axis Burgundy Private" is a credit card and a debit
        # card with different offers (coverage round 3, 27 Nov), and their pages must not share a title
        deb = " Debit" if o.instrument == "debit" and "debit" not in " ".join(vs).lower() else ""
        return f"{o.issuer} {' / '.join(v.title() if v.islower() else v for v in vs)}{deb}{net}"
    return f"{o.issuer} {kind}"


def mid(s: str) -> str:
    """'Select HSBC credit cards' inside a sentence."""
    return "s" + s[1:] if s.startswith("Select ") else s


def app_name(o: Offer) -> str:
    return PLATFORM.get(o.platform, o.platform.replace("chain:", "").title())


def where(o: Offer) -> str:
    p = app_name(o)
    w = {"app": f"{p} app", "web": f"{p} website"}.get(o.channel or "", p)
    return f"{w} · live events, not movies" if o.category == "events" else w


def what_full(o: Offer) -> str:
    """The benefit with its category when it isn't movies: '10% off live events' (QA F1)."""
    return what(o) + ("" if o.is_movie else " live events")


def what(o: Offer) -> str:
    v = o.value
    if o.kind == "bogo":
        return "1 ticket off" if o.category == "membership" else "2nd ticket free"
    if o.kind == "pct" and v.get("pct"):
        return f"{v['pct']}% off"
    if o.kind == "flat" and v.get("flat"):
        return f"₹{v['flat']:,} off"
    if o.kind == "cashback":
        return "Cashback"
    if o.kind == "complimentary" and v.get("free_tickets") and v.get("period") in PERIOD_WORDS:
        n = int(v["free_tickets"])
        return f"{n} free ticket{'' if n == 1 else 's'} {PERIOD_WORDS[v['period']]}"
    return o.kind.title()


def cap(o: Offer) -> str:
    t = o.cap_text or ""
    t = re.sub(r"₹(\d{4,})", lambda m: f"₹{int(m.group(1)):,}", t)
    return t or "cap: see terms"


def cap_tail(o: Offer) -> str:
    """" up to ₹250" after a benefit in running text; nothing after a flat ₹ amount whose terms state no cap, since
    "₹500 off cap: see terms" reads as a broken sentence and the amount is already the most it gives (decision 174)."""
    if o.kind == "flat" and o.value.get("flat") and cap(o) == "cap: see terms":
        return ""
    return f" {cap(o)}"


def cap_num(o: Offer) -> int:
    v = o.value
    return int(v.get("free_cap") or v.get("cap") or v.get("flat") or 0)


def next_day(today: date, key: str) -> date:
    return today + timedelta(days=(DAY_IDX[key] - today.weekday()) % 7)


def day_keys(o: Offer) -> list:
    return [d for d in o.days if d in DAY_IDX]


def day_rule(o: Offer, today: date):
    """The day rule as one chip: ('ok'|'wait'|'none', text). Static-safe (never 'today'); 'next Sat 28 Nov' is
    rewritten in the browser to the visitor's next such day by the freshness guard."""
    if "any" in o.days:
        return ("ok", "Every day")
    keys = day_keys(o)
    if len(keys) == 1:
        k = keys[0]
        n = next_day(today, k)
        lead = f"Book on {DAY[k]}s only" if o.day_basis == "booking" else f"{DAY[k]}s only"
        return ("wait", f"{lead} · {'next ' if n != today else ''}{DAY[k][:3]} {fmt_dm(n)}")
    if keys:
        return ("wait", " & ".join(DAY[k][:3] for k in sorted(keys, key=DAY_IDX.get)) + " only")
    return ("none", "Days not stated")


def ends_text(valid_to: date | None, today: date) -> str:
    """Validity as words, never a ticking timer: 'Ends 31 Dec', 'Ends in 5 days · 30 Nov', 'Last day · 25 Nov'."""
    if not valid_to:
        return "No end date"
    d = fmt_dm(valid_to) if valid_to.year == today.year else fmt_day(valid_to)
    n = (valid_to - today).days
    if n < 0:
        return f"Ended {d}"
    if n == 0:
        return f"Last day · {d}"
    if n <= 7:
        return f"Ends in {n} day{'s' if n != 1 else ''} · {d}"
    return f"Ends {d}"


def spend_gate(note: str | None) -> str | None:
    """'Needs ₹25,000 card spend in the past 3 months' from a quoted spend-gate note.
    Years are never amounts: a bare 4-digit 1900-2100 without ₹ or a comma is skipped."""
    if not note or "spend" not in note.lower():
        return None
    amount = None
    for rupee, num in re.findall(r"(₹|rs\.?\s*|inr\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})", note, re.I):
        n = int(num.replace(",", ""))
        if not rupee and "," not in num and 1900 <= n <= 2100:
            continue
        amount = n
        break
    months = re.search(r"(\d+|three|six)\s*(?:\(\d\)\s*)?(calendar\s+)?months", note, re.I)
    if amount is None:
        return "Needs a minimum card spend first (see terms)"
    m = {"three": "3", "six": "6"}.get(months.group(1).lower(), months.group(1)) if months else None
    cal = " calendar" if months and months.group(2) else ""
    return f"Needs ₹{amount:,} card spend in the previous {m}{cal} months" if m else f"Needs ₹{amount:,} card spend first"


def times(n: int) -> str:
    return {1: "Once a month", 2: "Twice a month"}.get(n, f"Up to {n} times a month")


def gate(o: Offer, today: date) -> str | None:
    """A condition beyond holding the card: booking day, paid pass, spend gate, minimum tickets."""
    keys = day_keys(o)
    if o.day_basis == "booking" and len(keys) == 1:
        n = next_day(today, keys[0])
        tail = " The show can be any day." if "any" in o.show_days else ""
        return f"Book on a {DAY[keys[0]]} ({'next: ' if n != today else ''}{fmt_dm(n)}).{tail}"
    if o.requires_purchase:
        m = re.search(r"\((\d+)\)\s+discounted tickets", o.quota_note or "")
        return f"Paid pass · {m.group(1)} tickets off per pass" if m else "Paid pass needed (see terms for limits)"
    g = spend_gate(o.quota_note)
    if g:
        return g
    if o.min_tickets and o.min_tickets >= 2:
        return f"Buy {o.min_tickets}+ tickets in one booking"
    return None


def gate_short(o: Offer, today: date) -> str | None:
    """The gate as a clause inside a sentence: 'when you book on a Saturday'."""
    keys = day_keys(o)
    if o.day_basis == "booking" and len(keys) == 1:
        return f"when you book on a {DAY[keys[0]]}"
    if o.requires_purchase:
        return "with a paid pass"
    g = spend_gate(o.quota_note)
    if g:
        return g[0].lower() + g[1:]
    if o.min_tickets and o.min_tickets >= 2:
        return f"for {o.min_tickets}+ tickets in one booking"
    return None


def cond_chips(o: Offer, today: date) -> list:
    """One row of condition chips: [(css class, text, extra attrs)]. The chip that trips people up is 'c-key'."""
    out = []
    k, t = day_rule(o, today)
    if not (o.category == "events" and k == "none"):
        out.append((f"today today-{k}" + (" c-key" if o.day_basis == "booking" and k == "wait" else ""), t, ""))
    if o.day_basis == "booking" and "any" in o.show_days and k == "wait":
        out.append(("", "Show can be any day", ""))
    out.append(("c-app", where(o).split(" · ")[0], ""))
    if o.category == "events":
        out.append(("c-key", "Live events, not movies", ""))
    if o.min_tickets and o.min_tickets >= 2 and not o.requires_purchase:
        out.append(("", f"Min {o.min_tickets} tickets", ""))
    if o.monthly_limit:
        out.append(("", times(o.monthly_limit), ""))
    if o.requires_purchase:
        m = re.search(r"\((\d+)\)\s+discounted tickets", o.quota_note or "")
        out.append(("c-key", f"Paid pass · {m.group(1)} tickets off per pass" if m else "Paid pass needed", ""))
    else:
        g = spend_gate(o.quota_note)
        if g:
            out.append(("c-key", g, ""))
    out.append((end_cls(o.valid_to, today), ends_text(o.valid_to, today), f' data-end="{o.valid_to.isoformat()}"' if o.valid_to else ""))
    return out


CD_DAYS = 7   # decision 170: the countdown shows from 7 days before the checked end date to the last day


def days_left(valid_to: date | None, today: date) -> int | None:
    return (valid_to - today).days if valid_to else None


def end_cls(valid_to: date | None, today: date) -> str:
    """'c-end', plus 'cd' (the countdown chip, decision 170) within CD_DAYS of the end and 'cd0' on the last day."""
    n = days_left(valid_to, today)
    return "c-end" + (" cd" if n is not None and 0 <= n <= CD_DAYS else "") + (" cd0" if n == 0 else "")


CARD_CHIPS = 3


def chip_rank(c: tuple) -> int:
    """Decision 149: the decisive conditions first: the day, the minimum, the gate (spend, paid pass, not movies),
    then the monthly limit, the end date, the show-day note. The app is in the value line, not a chip."""
    cls, text, _ = c
    if "today" in cls:
        return 0
    if "cd" in cls.split():
        return 0.5                    # decision 170: an offer about to end says so on the card, right after the day
    if text.startswith("Min "):
        return 1
    if "c-key" in cls:
        return 2
    if "c-end" in cls:
        return 4
    if text == "Show can be any day":
        return 1                      # the other half of a booking-day rule: kept with it
    return 3


def card_chips(o: Offer, today: date) -> list:
    """At most CARD_CHIPS chips on a card, decisive ones first; the rest are in Details (terms_lines)."""
    keep = sorted([c for c in cond_chips(o, today) if "c-app" not in c[0]], key=chip_rank)[:CARD_CHIPS]
    return sorted(keep, key=lambda c: cond_chips(o, today).index(c))   # shown in the reading order


def key_condition(o: Offer, today: date) -> str:
    """The ONE condition that trips people up. Never a tautology like 'Premier cardholders only'."""
    g = gate(o, today)
    if g:
        return g
    if o.monthly_limit:
        return times(o.monthly_limit)
    return "See the terms for conditions"


def tickets_line(o: Offer) -> str | None:
    """'For 2 / 3 / 4 tickets', strictly from the terms' fields. Never a savings figure."""
    if o.kind != "bogo":
        return None
    if o.category == "membership":
        low = " (the lowest-priced)" if "lowest_priced_ticket" in o.conditions else ""
        n = f"{o.min_tickets} or more" if o.min_tickets else "2 or more"
        return f"For {n} tickets: 1 ticket off{low}, {cap(o)}."
    first = f"For 2 tickets: 1 free, {cap(o)}."
    more = " For 3 or 4: the terms don't say more than 1 is free."
    return first + more


def terms_lines(o: Offer, warn: list) -> list[str]:
    out = []
    if o.variants and o.variants_scope == "listed":
        out.append(f"Cards: {', '.join(o.variants)}")
    elif o.variants_scope == "unstated":
        out.append("Selected cards (the terms don't list which)")
    if o.monthly_limit:
        out.append(times(o.monthly_limit))
    if o.min_tickets:
        out.append(f"Minimum {o.min_tickets} tickets in one booking")
    if "any" in o.days:
        out.append("Any day of the week")
    if o.quota_note:
        out.append(o.quota_note.rstrip("."))
    for c in o.conditions:
        if c in CONDITIONS:
            out.append(CONDITIONS[c])
        elif c.startswith("bins:"):
            out.append("Only cards whose first digits (BIN) are listed in the terms")
        else:
            warn.append(f"{o.id}: unknown condition code {c!r} (not shown)")
    for x in o.excludes:
        out.append(f"Not valid: {x}")
    if o.requires_purchase and o.cities:
        out.append(f"Pass sold in {len(o.cities)} cities, per the terms")
    out.append(f"Ends {fmt_day(o.valid_to)}" if o.valid_to else "No end date stated in the terms")
    return out


def domain(u: str) -> str:
    return urlparse(u).netloc.removeprefix("www.")


def quote_for(o: Offer) -> str | None:
    for k in ("value", "kind", "days", "quota_note"):
        q = o.quotes.get(k)
        if isinstance(q, (list, tuple)):    # a field may be backed by several verbatim spans (engine model.pieces)
            q = " … ".join(str(p).strip() for p in q if isinstance(p, str) and p.strip())
        if q and isinstance(q, str):
            return q
    return None


CHECKER = "FDFS Offer Intelligence"


def manual_source(o: Offer, cfg: dict) -> bool:
    """A source whose site bans automated reads (District's policy pages): never read automatically."""
    return o.raw.get("check_method") == "manual" or domain(o.source_url) in set(cfg.get("manual_hosts") or [])


def manual_recorded(o: Offer) -> bool:
    """090 sets check_method = "manual" only once a person has recorded a real check of the terms."""
    return o.raw.get("check_method") == "manual"


def publishable(o: Offer, at: datetime, cfg: dict) -> tuple[bool, str]:
    """The site's full guard: the export guard plus the manual-source hold. Used for pages AND the change log."""
    ok, why = shown(o, at)
    if ok and manual_source(o, cfg) and not manual_recorded(o):
        return False, "manual source: no check recorded by our team yet"
    return ok, why


def checked_by(o: Offer, cfg: dict) -> str:
    return f"{CHECKER} (terms read by our team)" if manual_source(o, cfg) else CHECKER


def join_and(items: list) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def fit_title(cands: list[str]) -> str:
    for c in cands:
        t = f"{c} · FDFS"
        if len(t) <= 65:
            return t
    return cands[-1][:57].rstrip() + " · FDFS"


# ---------------------------------------------------------------- page shell
@dataclass
class Page:
    path: str
    title: str
    desc: str
    h1: str
    answer: str
    body: str
    crumbs: list
    stamp_kind: str
    stamp: datetime
    content_key: str
    noindex: bool = False
    hero: str = ""
    css: str = ""
    og: dict | None = None        # {"name", "lines": [...]} for a per-page card; None = brand card
    extra_ld: list = field(default_factory=list)
    canonical: bool = True
    title_options: tuple | None = None
    js: str = ""                  # page-only script (after the guard)
    published: datetime | None = None   # Article datePublished (weekly digest)


BRAND_OG_ALT = "FDFS: movie ticket offers. bookmyfdfs.in."



_SVG_NUM = re.compile(r"-?\d+\.\d+")


def svg_tight(d: str) -> str:
    """Round decimal numbers in SVG path data or a transform to one decimal, without changing its shape."""
    def one(m):
        t = f"{round(float(m.group()), 1):.1f}".rstrip("0").rstrip(".")
        t = "0" if t in ("-0", "") else t
        return t.replace("0.", ".", 1) if t.startswith(("0.", "-0.")) else t
    return _SVG_NUM.sub(one, d)


class Site:
    def __init__(self, root: Path, cfg: dict, now: datetime, banks: list):
        self.root, self.cfg, self.now, self.banks = root, cfg, now, banks
        self.base = cfg["base_url"].rstrip("/")
        # 26 Nov (publish gate): the mark and wordmark ship inline on every page (header and footer), so their path
        # numbers are kept to one decimal. That is under 0.06 px at the size they're drawn, and saves about 0.8 KB gzip.
        mb = json.loads((root / "brand/logo/mark-b.parts.json").read_text())
        self.mb = {k: [svg_tight(d) for d in v] if k in ("seats", "letters") else v for k, v in mb.items()}
        head, word = (root / "brand/logo/wordmark-fdfs.path.txt").read_text().strip().split("\n", 1)
        self.ww, self.wh = head.split()[-2:]
        self.word = svg_tight(word.strip())
        self.og_render = False
        self.css_v = "0"
        self.apps: list = []          # [(hub path, app name)] for hubs that exist (>= 1 checked offer)
        self.week: str | None = None  # /this-week/ when this week's digest exists
        self.bank_apps: dict = {}     # bank slug -> app keys with a bank x app page
        self.meta: dict = {}          # top-level feed fields for the home adapter (009 A1, A2)
        self.plan_offers: list = []   # P3: the shown offers (checklist examples), and gone offers' records for Saved
        self.plan_gone: dict = {}
        self.cards: list = []         # [(path, card name, bank slug)] for card pages that exist (decision 144)
        self.days: list = []          # [(path, label)] for weekday pages that exist (decision 146)
        self.guide: str | None = None  # the pillar guide's path when it exists (decision 147)
        self.offers: list = []        # the shown offers (alternatives on gone offer pages, decision 148)

    def bank_name(self, issuer: str) -> str:
        return (self.cfg.get("issuer_names") or {}).get(issuer, issuer)

    def mark(self, cls="mk", ref=False):
        # 26 Nov (publish gate): the header draws the mark once in <g id="fdfs-mk">; the footer reuses it with <use>
        # instead of a second copy. The mark's CSS (.mk-s, .mk-s3, .mk-l) doesn't depend on where it sits, so both match.
        head = f'<svg class="{cls}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
        if ref:
            return head + '<use href="#fdfs-mk"/></svg>'
        seats = "".join(f'<path class="mk-s mk-s{i}" d="{d}"/>' for i, d in enumerate(self.mb["seats"]))
        return f'{head}<g id="fdfs-mk">{seats}<g class="mk-l">{"".join(self.mb["letters"])}</g></g></svg>'

    def jsonld(self, p: Page) -> str:
        url = self.base + p.path
        org = {"@type": "Organization", "@id": self.base + "/#org", "name": self.cfg["name"], "url": self.base + "/",
               "alternateName": self.cfg["alternate_names"], "logo": self.base + "/assets/brand/app-icon-512.png",
               "description": "Independent site that checks movie-ticket offers against official terms."}
        site = {"@type": "WebSite", "@id": self.base + "/#site", "name": self.cfg["name"], "url": self.base + "/",
                "alternateName": self.cfg["alternate_names"], "publisher": {"@id": self.base + "/#org"},
                "inLanguage": "en-IN"}
        webpage = {"@type": "WebPage", "@id": url, "url": url, "name": p.title, "description": p.desc,
                   "isPartOf": {"@id": self.base + "/#site"}, "inLanguage": "en-IN", "dateModified": iso(p.stamp)}
        graph = [org, site, webpage]
        if len(p.crumbs) >= 2:
            graph.append({"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": n, "item": self.base + pth}
                for i, (n, pth) in enumerate(p.crumbs)]})
        graph += p.extra_ld
        out = json.dumps({"@context": "https://schema.org", "@graph": graph},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        # inside <script>: a scraped "</script>" or "<!--" must not end the block (JSON still parses the same)
        return out.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    def og_meta(self, p: Page) -> str:
        if p.og and self.og_render:
            img, alt = f"/og/{p.og['name']}.png", og_alt(p.og["lines"])
        else:
            img, alt = "/og/brand.png", BRAND_OG_ALT
        return (f'<meta property="og:image" content="{self.base}{img}">'
                f'<meta property="og:image:alt" content="{E(alt)}">'
                '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
                '<meta property="og:locale" content="en_IN"><meta name="twitter:card" content="summary_large_image">')

    def render(self, p: Page) -> str:
        html_ = self._render(p)
        head, sep, body = html_.partition("</head>")

        def key(dm: str) -> str:
            t = datetime.strptime(f"{dm} {self.now.year}", "%d %b %Y").date()
            if t < self.now.date() - timedelta(days=200):
                t = t.replace(year=t.year + 1)
            return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[t.weekday()]

        def wrap(m):
            return ">" + re.sub(r"((?:next:? |(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ))(\d{1,2} [A-Z][a-z]{2})\b",
                                lambda x: f'{x.group(1)}<span data-next="{key(x.group(2))}">{x.group(2)}</span>', m.group(1)) + "<"
        return head + sep + re.sub(r">([^<]+)<", wrap, body)

    def _render(self, p: Page) -> str:
        cfg = self.cfg
        cur = ' aria-current="page"'
        nav_items = (("/", "Offers"), ("/calendar/", "Calendar"), ("/best-card-for-movie-tickets/", "Best card"), ("/how-we-check/", "How we check"))
        nav = "".join(f'<a href="{h}"{cur if h == p.path else ""}>{t}</a>' for h, t in nav_items)
        crumbs = ""
        if len(p.crumbs) > 1:
            crumbs = ('<nav class="crumbs wrap" aria-label="Breadcrumb"><ol>' + "".join(
                f'<li><a href="{pth}">{E(n)}</a></li>' if i < len(p.crumbs) - 1 else f'<li aria-current="page">{E(n)}</li>'
                for i, (n, pth) in enumerate(p.crumbs)) + "</ol></nav>")
        analytics = ""
        if cfg.get("analytics") and cfg["analytics"].get("cloudflare_token"):
            tok = E(cfg["analytics"]["cloudflare_token"])
            analytics = (f"<script defer src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
                         f"data-cf-beacon='{{\"token\": \"{tok}\"}}'></script>")
        robots = '<meta name="robots" content="noindex,follow">\n' if p.noindex else ""
        canonical = f'<link rel="canonical" href="{self.base}{p.path}">\n' if p.canonical else ""
        bank_links = "".join(f'<a href="/bank/{s}/">{E(self.bank_name(n))} offers</a>' for s, n in self.banks)
        app_links = "".join(f'<a href="{pth}">{E(n)} offers</a>' for pth, n in self.apps) + \
            (f'<a href="{self.week}">This week</a>' if self.week else "")
        foot_links = "".join(f'<a href="{h}">{t}</a>' for h, t in (
            ("/", "Offers"), ("/best-card-for-movie-tickets/", "Best credit card for movie tickets"), ("/changes/", "Changes"),
            ("/how-we-check/", "How we check"), ("/about/", "About"), ("/corrections/", "Corrections"),
            ("/disclosures/", "Disclosures"), ("/offers.json", "Open data"), ("/agents/", "For agents")))
        guide_links = (f'<a href="{self.guide}">How card offers work</a>' if self.guide else "") + \
            "".join(f'<a href="{pth}">{E(lab)}</a>' for pth, lab in self.days)
        return f'''<!doctype html>
<html lang="en-IN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(p.title)}</title>
<meta name="description" content="{E(meta_desc(p.desc))}">
{canonical}{robots}<meta name="theme-color" content="#F6F5EE" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0F1813" media="(prefers-color-scheme: dark)">
<link rel="icon" href="/assets/brand/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link rel="alternate" type="application/atom+xml" title="FDFS offer changes" href="/changes.xml">
<meta property="og:type" content="website"><meta property="og:site_name" content="FDFS">
<meta property="og:title" content="{E(p.title)}"><meta property="og:description" content="{E(meta_desc(p.desc))}">
<meta property="og:url" content="{self.base}{p.path}">{self.og_meta(p)}
<link rel="preload" href="/assets/fonts/google-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/bricolage-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/site.css?v={self.css_v}">
<script>{HEAD_JS}</script>
{f"<style>{p.css}</style>" if p.css else ""}
<script type="application/ld+json">{self.jsonld(p)}</script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="hall">
<header><div class="wrap top"><a class="brand" href="/" aria-label="FDFS home">{self.mark()}<svg class="wm" viewBox="0 0 {self.ww} {self.wh}" aria-hidden="true"><path d="{self.word}"/></svg></a>
<nav class="nav" aria-label="Main">{nav}{HEADER_SEARCH}<button class="theme" type="button" aria-label="Switch theme"><svg class="ic i-moon" viewBox="0 0 20 20" aria-hidden="true"><path d="M16 12.5A6.5 6.5 0 0 1 7.5 4a6.5 6.5 0 1 0 8.5 8.5z" fill="currentColor"/></svg><svg class="ic i-sun" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="3.6" fill="currentColor"/><path d="M10 1.5v2.2M10 16.3v2.2M1.5 10h2.2M16.3 10h2.2M4 4l1.5 1.5M14.5 14.5 16 16M4 16l1.5-1.5M14.5 5.5 16 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button></nav></div></header>
<section class="hero{'' if p.path == '/' else ' hero-sm'} wrap" aria-labelledby="h1">
<div class="hero-copy">{p.hero}<h1 id="h1">{p.h1}</h1></div>
<div class="{'stage' if p.path == '/' else 'stage-sm'}"><div class="ticket answer" id="answer">
<p class="s-q"><span class="live"></span>{p.stamp_kind} <time datetime="{iso(p.stamp)}" data-stamp>{fmt_stamp(p.stamp)}</time></p>
<p class="s-a">{p.answer}</p>
</div></div>
</section>
</div>
{crumbs}
<main id="main">
{p.body}
</main>
<footer class="foot"><div class="wrap foot-in">
<div class="foot-brand">{self.mark("mk mk-foot", ref=True)}<div><p class="foot-name">FDFS</p><p class="foot-tag">{E(cfg["tagline"])}</p></div></div>
<nav class="foot-nav" aria-label="Site">{foot_links}</nav>
{f'<nav class="foot-nav foot-banks" aria-label="Offers by app"><span>Offers by app:</span>{app_links}</nav>' if app_links else ""}
{f'<nav class="foot-nav foot-banks" aria-label="Offers by bank"><span>Offers by bank:</span>{bank_links}</nav>' if bank_links else ""}
{f'<nav class="foot-nav foot-banks" aria-label="Guides"><span>Guides:</span>{guide_links}</nav>' if guide_links else ""}
<p class="foot-legal"><strong>{FOOTER_LINE}</strong><br>
Offers change. Read the terms on the bank's or app's page before you pay. Names of banks and apps are used only to say where an offer applies. Offer data: <a href="/offers.json">CC BY 4.0</a>. Quoted terms remain their owners&#x27;; the licence covers FDFS&#x27;s compilation and structure.</p>
</div></footer>
<script>{TAIL_JS}</script>
<script src="/assets/search.js?v={content_hash(HS_JS)[:8]}" defer></script>
<script data-guard>{GUARD_JS}</script>
{f"<script>{p.js}</script>" if p.js else ""}
{analytics}
</body>
</html>
'''


# decision 170: search from every page's header. Without JS it's a plain form that opens home filtered (/?q=); with JS
# it answers as you type from /search.json (checked offers and our pages only, fetched once on first open, same site).
HEADER_SEARCH = ('<details class="hs"><summary class="hs-b" title="Search offers"><svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m10.5 10.5 3.6 3.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span class="sr">Search offers</span></summary>'
                 '<form class="hs-f" action="/" role="search"><label class="hs-l" for="hs-q">Search checked offers by bank, card or app</label>'
                 '<input id="hs-q" name="q" type="search" autocomplete="off" enterkeyhint="search" maxlength="80">'
                 '<button class="hs-go" type="submit">Search</button><ul class="hs-r" hidden></ul></form></details>')
# 26 Nov (publish gate): the open panel's styles live here, not in site.css, so every page carries fewer bytes.
HS_CSS = '.hs-f{position:absolute;left:var(--gutter,16px);right:var(--gutter,16px);top:calc(100% - 4px);z-index:40;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:12px;border:1px solid var(--line);border-radius:16px;background:var(--surface);box-shadow:var(--shadow-1)}.hs-l,.hs-r{grid-column:1/-1;font-size:var(--t-xs);color:var(--text-2)}.hs-f input,.hs-go{min-height:44px;border-radius:12px;font:inherit}.hs-f input{min-width:0;padding:0 12px;border:1px solid var(--line);background:var(--surface);color:var(--text);font-size:16px}.hs-go{padding:0 16px;border:0;background:var(--accent);color:var(--ink);font-weight:700;cursor:pointer}.hs-r{list-style:none;margin:0;padding:0;max-height:60vh;overflow-y:auto}.hs-r[hidden]{display:none}.hs-r a,.hs-r p{display:block;margin:0;padding:10px 8px;min-height:44px;border-top:1px solid var(--line);color:var(--text);text-decoration:none}.hs-r a:hover,.hs-r a:focus{background:var(--surface-2)}.hs-r b{display:block;font-size:var(--t-sm)}.hs-r span{display:block}'
HS_JS = ("(function(){var h=document.querySelector('.hs');if(!h)return;var c=document.createElement('style');c.textContent=HS_CSS_JSON;document.head.appendChild(c);var f=h.querySelector('form'),q=f.q,r=h.querySelector('.hs-r'),I=null,P=null;"
         "function load(){return P||(P=fetch('/search.json').then(function(x){return x.json()}).then(function(j){I=j.items||[]},function(){P=null;I=null}))}"
         "function li(a,b,u){var l=document.createElement('li'),e=document.createElement(u?'a':'p');if(u)e.href=u;"
         "var t=document.createElement('b');t.textContent=a;e.appendChild(t);if(b){var s=document.createElement('span');s.textContent=b;e.appendChild(s)}l.appendChild(e);r.appendChild(l)}"
         "function show(){var v=q.value.toLowerCase().trim(),w=v.split(/\\s+/).filter(Boolean);r.textContent='';if(!w.length){r.hidden=true;return}"
         "if(!I){li('Loading\u2026');r.hidden=false;load().then(show);return}"
         "var m=I.filter(function(x){var k=(x.t+' '+x.s+' '+x.k).toLowerCase();return w.every(function(y){return k.indexOf(y)>-1})}).slice(0,8);"
         "m.forEach(function(x){li(x.t,x.s,x.u)});if(!m.length)li('No checked offer matches','Press Search to filter every offer');r.hidden=false}"
         "h.addEventListener('toggle',function(){if(h.open){load();q.focus()}});q.addEventListener('input',show);"
         "h.addEventListener('keydown',function(e){if(e.key=='Escape'){h.open=false;h.querySelector('summary').focus()}});"
         "document.addEventListener('click',function(e){if(h.open&&!h.contains(e.target))h.open=false})})();")
HS_JS = HS_JS.replace("HS_CSS_JSON", json.dumps(HS_CSS))


def search_index(site: "Site", offers: list, pages: list) -> dict:
    """Decision 170: what the header search answers from. Checked offers and the pages we publish: never a spotted lead."""
    def k(*xs):
        return " ".join(str(x) for x in xs if x).lower()
    items = []
    for o in sorted(offers, key=home_order):
        extra = "bogo buy 1 get 1 buy one get one" if o.kind == "bogo" else ""
        items.append({"t": f"{who(o)} on {app_name(o)}", "s": f"{what(o)}, {cap(o)}",
                      "u": offer_path(o.id), "k": k(o.issuer, site.bank_name(o.issuer), " ".join(o.variants), o.category,
                                                    " ".join(DAY[d] for d in day_keys(o)), extra, "live events" if o.category == "events" else "")})
    live_paths = {p.path for p in pages if not p.noindex}
    for s_, n in site.banks:
        if f"/bank/{s_}/" in live_paths:
            c = sum(1 for o in offers if o.is_bank and o.slug == s_)
            items.append({"t": f"{site.bank_name(n)} offers", "s": f"{c} checked offer{'s' if c != 1 else ''}",
                          "u": f"/bank/{s_}/", "k": k(n, s_, "bank")})
    for pth, n in site.apps:
        items.append({"t": f"{n} offers", "s": "Every checked offer on this app", "u": pth, "k": k(n, "app")})
    for pth, n, _ in site.cards:
        if pth in live_paths:
            items.append({"t": f"{n} offers", "s": "This card on every app", "u": pth, "k": k(n, "card")})
    for pth, lab in site.days:
        items.append({"t": lab, "s": "Offers whose terms name this day", "u": pth, "k": k(lab, "day")})
    for pth, t, s_, kw in (("/calendar/", "Calendar", "Which offer to book on which day", "week plan calendar"),
                           ("/best-card-for-movie-tickets/", "Best card for movie tickets", "Grouped by benefit", "best credit card"),
                           (site.guide, "How card offers work", "Caps, minimums, limits", "guide how"),
                           ("/agents/", "Use FDFS from an assistant or agent", "MCP server and data feeds", "mcp ai agent assistant api json")):
        if pth and pth in live_paths:
            items.append({"t": t, "s": s_, "u": pth, "k": kw})
    return {"v": 1, "items": items}


# Freshness guard (<1 KB): the static text is right on build day; this keeps it honest after that.
# Next Saturday from the visitor's IST date; a card unchecked for 7+ days or past its end date says so
# and drops its day chip. With JS off the build-time text stays (fine for <= 7 days between live runs).
GUARD_JS = ("(function(){var q=/[?&]fdfs_now=(\\d+)/.exec(location.search),n=q?+q[1]:Date.now(),D=864e5,"
            "i=new Date(n+198e5),y=i.toISOString().slice(0,10);"
            "document.querySelectorAll('[data-checked]').forEach(function(c){var v=c.dataset.validTo,m=v&&y>v?'Ended · see terms':"
            "n-Date.parse(c.dataset.checked)>7*D?'Not re-checked recently · see terms':0;if(!m)return;c.classList.add('stale');"
            "if(c.hasAttribute('data-sat-hero'))c.hidden=true;var p=c.querySelector('.o-stale');if(p){p.textContent=m;p.hidden=false}"
            "if(c.tagName=='TR')c.cells[0].insertAdjacentHTML('beforeend','<small> · '+m.split(' · ')[0]+'</small>');"
            "c.querySelectorAll('.today').forEach(function(x){x.hidden=true})});"
            "document.querySelectorAll('[data-next]').forEach(function(e){var c=e.closest('[data-checked]'),"
            "s=new Date(i.getTime()+('sun mon tue wed thu fri sat'.indexOf(e.dataset.next)/4-i.getUTCDay()+7)%7*D);"
            "if(!c||!c.classList.contains('stale'))e.textContent=s.getUTCDate()+' '+s.toUTCString().slice(8,11)})})();")
HEAD_JS = ("(function(){var d=document.documentElement,q=/[?&]theme=(light|dark)/.exec(location.search),t=null;d.classList.add('js');"
           "try{t=localStorage.getItem('fdfs-theme')}catch(e){}if(q)t=q[1];if(t)d.setAttribute('data-theme',t)})();")
# Shared by every page: the theme toggle; Copy (a button: it never navigates or opens anything; "✓ Copied" for 2 s,
# with a select-and-copy fallback); and "Ends in N days" recomputed for the visitor's IST day.
TAIL_JS = ("(function(){var d=document.documentElement,b=document.querySelector('.theme');"
           "function dark(){var t=d.getAttribute('data-theme');return t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches}"
           "function lab(){b.setAttribute('aria-label',dark()?'Use light theme':'Use dark theme')}"
           "if(b){lab();b.addEventListener('click',function(){var t=dark()?'light':'dark';d.setAttribute('data-theme',t);"
           "try{localStorage.setItem('fdfs-theme',t)}catch(e){}lab()})}"
           "document.addEventListener('click',function(e){var c=e.target.closest('[data-copy]');if(!c)return;"
           "var l=c.querySelector('.cl'),v=c.getAttribute('data-copy'),w=c._w||(c._w=l.textContent);"
           "function ok(){c.classList.add('done');l.textContent='\u2713 Copied';clearTimeout(c._t);"
           "c._t=setTimeout(function(){c.classList.remove('done');l.textContent=w},2000)}"
           "function fb(){var t=document.createElement('textarea'),r=false;t.value=v;t.setAttribute('readonly','');"
           "t.style.cssText='position:fixed;top:0;opacity:0';document.body.appendChild(t);t.select();"
           "try{r=document.execCommand('copy')}catch(x){}t.remove();if(r)ok();else l.textContent='Select the code to copy'}"
           "if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(v).then(ok,fb);else fb()});"
           # decision 164: Share opens the phone's share sheet, else copies the link; Add to calendar builds an .ics here
           "function tmp(l,m){var w=l._w||(l._w=l.textContent);l.textContent=m;clearTimeout(l._t);l._t=setTimeout(function(){l.textContent=w},2500)}"
           "document.querySelectorAll('[data-share]').forEach(function(b){if(!navigator.share)b.querySelector('.sl').textContent='Copy link'});"
           "document.addEventListener('click',function(e){var b=e.target.closest('[data-share]');if(!b)return;var u=b.dataset.url,l=b.querySelector('.sl');"
           "if(navigator.share){navigator.share({title:document.title,text:b.dataset.share,url:u}).catch(function(){});return}"
           "if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(u).then(function(){tmp(l,'\u2713 Link copied')},function(){tmp(l,u)});else tmp(l,u)});"
           "var q=/[?&]fdfs_now=(\\d+)/.exec(location.search),T=Math.floor(((q?+q[1]:Date.now())+198e5)/864e5),"
           "M='Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ');"
           "document.querySelectorAll('[data-end]').forEach(function(e){var x=new Date(e.dataset.end),n=Math.round(x/864e5)-T,"
           "y=new Date(T*864e5).getUTCFullYear(),s=x.getUTCDate()+' '+M[x.getUTCMonth()]+(x.getUTCFullYear()!=y?' '+x.getUTCFullYear():'');"
           "e.classList.toggle('cd',n>=0&&n<8);e.classList.toggle('cd0',n==0);e.textContent=n<0?'Ended '+s:n==0?'Last day \u00b7 '+s:n<8?'Ends in '+n+' day'+(n>1?'s':'')+' \u00b7 '+s:'Ends '+s})})();")


# decision 164: offer pages only. Add to calendar: an all-day .ics made in the browser (nothing is sent anywhere)
ICS_JS = ("(function(){function tmp(l,m){var w=l._w||(l._w=l.textContent);l.textContent=m;clearTimeout(l._t);"
          "l._t=setTimeout(function(){l.textContent=w},2500)}"
           "document.addEventListener('click',function(e){var b=e.target.closest('[data-ics]');if(!b)return;"
           "var q=/[?&]fdfs_now=(\\d+)/.exec(location.search),t=new Date((q?+q[1]:Date.now())+198e5),K='sun mon tue wed thu fri sat'.split(' '),"
           "ks=b.dataset.k.split(' '),to=b.dataset.to,d=null,i,x;"
           "if(b.dataset.ics=='day'){for(i=0;i<14;i++){x=new Date(t.getTime()+i*864e5);if(ks.indexOf(K[x.getUTCDay()])>-1){d=x;break}}}else d=new Date(to+'T00:00:00Z');"
           "var l=b.querySelector('.sl');if(!d||(to&&d.toISOString().slice(0,10)>to)){tmp(l,'No booking day left');return}"
           "var f=function(z){return z.toISOString().slice(0,10).replace(/-/g,'')},n=new Date(d.getTime()+864e5),"
           "esc=function(s){return s.replace(/([,;\\\\])/g,'\\\\$1')},"
           "ics=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//FDFS//bookmyfdfs.in//EN','BEGIN:VEVENT','UID:'+f(d)+'-'+b.dataset.url.length+'@bookmyfdfs.in',"
           "'DTSTAMP:'+f(new Date())+'T000000Z','DTSTART;VALUE=DATE:'+f(d),'DTEND;VALUE=DATE:'+f(n),'SUMMARY:'+esc(b.dataset.t),"
           "'DESCRIPTION:'+esc('Check the terms before you book: '+b.dataset.url),'URL:'+b.dataset.url,'END:VEVENT','END:VCALENDAR'].join('\\r\\n'),"
           "a=document.createElement('a');a.href=URL.createObjectURL(new Blob([ics],{type:'text/calendar'}));a.download='fdfs-offer.ics';"
           "document.body.appendChild(a);a.click();a.remove();tmp(l,'\u2713 Saved for '+d.getUTCDate()+' '+'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ')[d.getUTCMonth()])});"
          "})();")


# decision 165: "New since your last visit". The ids of the offers listed at the last visit stay in this browser's
# localStorage (nothing else, never sent anywhere). On the next visit, offers that weren't listed then get a "New"
# badge and the list says how many. A first visit shows nothing.
NEW_JS = ("(function(){try{var k='fdfs-seen',a=[].map.call(document.querySelectorAll('#offers .offer[id]'),function(e){return e.id});"
          "if(!a.length)return;var s=JSON.parse(localStorage.getItem(k)||'null');localStorage.setItem(k,JSON.stringify({ids:a}));"
          "if(!s||!s.ids)return;var n=a.filter(function(i){return s.ids.indexOf(i)<0});if(!n.length)return;"
          "n.forEach(function(i){var b=document.createElement('span');b.className='nb';b.textContent='New';"
          "document.getElementById(i).querySelector('.o-head').appendChild(b)});var p=document.querySelector('[data-new]');"
          "if(p){p.textContent=n.length+' new offer'+(n.length>1?'s':'')+' since your last visit, marked New';p.hidden=false}}catch(e){}})();")


def llms_full(base: str, offers: list, now: datetime) -> str:
    """Decision 167: every offer that passes our checks, as plain text an answer engine can quote. Built only from
    offers.json (the page guard's verified set) and the issuers' own words. Nothing Spotted."""
    today = now.astimezone(IST).date()
    out = [f"# FDFS: movie and live event ticket offers in India, checked against the issuer's terms\n\n"
           f"> {len(offers)} offers, generated {fmt_stamp(now)}. Each was read on the issuer's own terms page; the "
           f"quotes below are the issuer's words. Licence CC BY 4.0: credit \"FDFS (bookmyfdfs.in)\" and link the "
           f"offer's page. Quoted terms remain their owners'.\n"]
    for o in sorted(offers, key=lambda x: (not x.is_movie, x.issuer, x.id)):
        qs = []
        for qv in o.quotes.values():
            for q in (qv if isinstance(qv, list) else [qv]):
                if isinstance(q, str) and len(q.strip()) >= 30 and q.strip() not in qs:
                    qs.append(q.strip())
        lines = [f"\n## {who(o)} on {app_name(o)}: {what_full(o)}\n",
                 f"- Page: {base}{offer_path(o.id)}",
                 f"- Benefit: {what(o)}, {cap(o)}" + (" (live event tickets, not movies)" if not o.is_movie else ""),
                 f"- Key condition: {key_condition(o, today)}",
                 f"- Dates: {validity_text(o)}"]
        if o.code:
            lines.append(f"- Code: {o.code}")
        lines += [f"- Terms: {o.source_url}",
                  f"- Checked: {fmt_stamp(o.checked_at)}"]
        lines += [f"- Quote: \"{q}\"" for q in qs[:4]]
        out.append("\n".join(lines) + "\n")
    return "".join(out)


def _min_js(src: str) -> str:
    """Tiny, conservative JS minifier (stdlib only): drops comments and the whitespace that isn't needed between two
    word characters. String and regex literals pass through untouched; line breaks are kept where a statement could
    end without a semicolon (after ) ] } or a word), so automatic semicolon insertion never changes meaning."""
    out, i, n, prev = [], 0, len(src), ""
    word = re.compile(r"[A-Za-z0-9_$\u0080-\uffff]")
    pend_space = pend_nl = False
    while i < n:
        c = src[i]
        if src.startswith("/*", i):
            i = src.index("*/", i) + 2
            pend_space = True
            continue
        if src.startswith("//", i) and (not prev or prev in "(,=:[!&|?{};\n"):
            i = src.find("\n", i) if "\n" in src[i:] else n
            continue
        if c in " \t\r\n":
            pend_nl = pend_nl or c == "\n"
            pend_space = True
            i += 1
            continue
        if pend_space and out:
            last = out[-1][-1]
            if pend_nl and (word.match(last) or last in ")]}'\"/") and (word.match(c) or c in "([{'\"/+-!~`"):
                out.append("\n")
            elif word.match(last) and word.match(c):
                out.append(" ")
        pend_space = pend_nl = False
        if c in "'\"`":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif c == "/" and (not prev or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, cls = i + 1, False
            while cls or src[j] != "/":
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                j += 1
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            out.append(src[i:j])
            i = j
        else:
            out.append(c)
            i += 1
        prev = out[-1][-1]
    return "".join(out).strip()


HOME_JS = _min_js((Path(__file__).resolve().parent / "home.js").read_text(encoding="utf-8"))


# L2 (decision 142, handoff 009 A1-A5): the raw fields the home.js adapter reads. Contract fields that the feed doesn't
# carry yet (card_products, requires_card, min_tickets_basis, max_benefit_per_booking, freshness) are passed through only
# when present; the adapter derives the agreed fallbacks. Cards never leave the visitor's device.
FEED_KEYS = ("issuer", "card_variants", "variants_scope", "network", "card_products", "requires_card", "min_tickets",
             "min_tickets_basis", "max_benefit_per_booking", "freshness", "valid_from", "kind", "day_basis")
# checked_at and valid_to are already on each card (data-checked, data-valid-to): the adapter reads them there.
FEED_TOP = ("freshness_policy", "issuers")


def feed_js(offers: list, meta: dict) -> str:
    rows = {o.id: {k: o.raw[k] for k in FEED_KEYS if k in o.raw and o.raw[k] not in (None, [], "")} for o in offers}
    for o in offers:
        if rows[o.id].get("card_variants"):                # display names for My cards (clean_variant)
            rows[o.id]["card_variants"] = [clean_variant(o.issuer, v) for v in rows[o.id]["card_variants"]]
        if "requires_card" in o.raw:                    # false/null are meaningful (A3): keep them as given
            rows[o.id]["requires_card"] = o.raw["requires_card"]
    feed = {"rows": rows, **{k: meta[k] for k in FEED_TOP if meta.get(k)}}
    lit = json.dumps(feed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    return f"var FDFS_FEED={lit};"


def home_js() -> str:
    """The home page script, with the shared bank vocabulary (one source for cards, search and "My cards")."""
    banks = {b: n + "|" + " ".join(x.replace(" ", "_") for x in al if x != b) for b, n, _, _, al in BANKS}
    lit = json.dumps(banks, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f"var FDFS_BANKS={lit};\n{HOME_JS}"


# ---------------------------------------------------------------- components
def icon(name: str) -> str:
    paths = {
        "check": '<path d="M3 8.5 6.5 12 13 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
        "out": '<path d="M6 3h7v7M13 3 4 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        "cal": '<rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M2 7h12M5 1.5v3M11 1.5v3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
        "copy": '<rect x="5" y="5" width="8.5" height="8.5" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 10.5V3.8C3 3.3 3.3 3 3.8 3h6.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
        "card": '<rect x="1.5" y="3.5" width="13" height="9" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M1.5 6.5h13" stroke="currentColor" stroke-width="1.8"/>',
        "pass": '<path d="M2.5 4.5h11v2a1.6 1.6 0 0 0 0 3v2h-11v-2a1.6 1.6 0 0 0 0-3z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
        "arrow": '<path d="M3 8h10M9 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        "search": '<circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m10.5 10.5 3.6 3.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
        "send": '<path d="M8 10V2.2M5 5l3-3 3 3M3.5 8v5.5h9V8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        "share": '<path d="M8 1.8a6.2 6.2 0 0 0-5.3 9.4L2 14.2l3.1-.8A6.2 6.2 0 1 0 8 1.8z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
    }
    return f'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true">{paths[name]}</svg>'


SEAT = ('<svg class="seat{x}" viewBox="0 0 20 16"><path d="M4 2.5h12a1.5 1.5 0 0 1 1.5 1.5v6H2.5V4A1.5 1.5 0 0 1 4 2.5z'
        'M1 9.5h18v3H1zM3 12.5V15M17 12.5V15" fill="currentColor"/></svg>')


WA_LABEL = '<span><span class="sr">Share on </span>WhatsApp</span>'


def share_button(text: str, url: str) -> str:
    """Decision 164: the phone's own share sheet (WhatsApp, Messages, Instagram, email...), or "Copy link" where the
    browser has no share sheet. JS only (`.js-only`), so it never shows as a dead button. The text is built from
    verified fields only, and the URL carries no tracking parameter."""
    return (f'<button class="share js-only" type="button" data-share="{E(text)}" data-url="{E(url)}">'
            f'{icon("send")}<span class="sl">Share</span></button>')


def share_row(text: str, url: str, extra: str = "") -> str:
    """Decision 164: a page-level share row (bank and offer pages): WhatsApp works without JS; the share sheet or Copy
    link with JS; `extra` takes the offer page's Add to calendar button."""
    wa = "https://wa.me/?text=" + quote_url(f"{text} {url}")
    return (f'<div class="wrap shr" role="group" aria-label="Share or save">'
            f'{ext(wa, icon("share") + WA_LABEL, cls="share")}{share_button(text, url)}{extra}</div>')


def ics_button(o: "Offer", url: str) -> str:
    """Decision 164: Add to calendar, built in the browser from the page's own data. A day-tied booking offer gets an
    all-day event on the next booking day; any other offer with an end date gets one on its last day. Nothing is
    sent anywhere: the browser makes the .ics file and the phone's calendar opens it."""
    ks = [] if "any" in o.days else day_keys(o)
    if ks and o.day_basis != "show":
        mode, label = "day", f"Book: {who(o)} on {where(o).split(' · ')[0]}, {what(o)} {cap(o)}"
    elif o.valid_to:
        mode, label = "end", f"Last day: {who(o)} on {where(o).split(' · ')[0]}, {what(o)} {cap(o)}"
    else:
        return ""
    return (f'<button class="share js-only" type="button" data-ics="{mode}" data-k="{" ".join(ks)}"'
            f' data-to="{o.valid_to.isoformat() if o.valid_to else ""}" data-t="{E(label)}" data-url="{E(url)}">'
            f'{icon("cal")}<span class="sl">Add to calendar</span></button>')


def until_text(o: "Offer", today: date) -> str:
    """Decision 170: ' Valid until 31 Dec.' for shared text, from the checked end date; '' when the terms give none."""
    if not o.valid_to:
        return ""
    return f" Valid until {fmt_dm(o.valid_to) if o.valid_to.year == today.year else fmt_day(o.valid_to)}."


def cd_pill(o: "Offer", today: date) -> str:
    """Decision 170: the offer page's countdown, above the headline, from the checked end date. Built with the page
    (so nothing moves on load) and recomputed for the visitor's IST day by the shared script. Never a ticking timer."""
    n = days_left(o.valid_to, today)
    if n is None or not 0 <= n <= CD_DAYS:
        return ""
    return f'<p class="cd-pill" data-end="{o.valid_to.isoformat()}">{E(ends_text(o.valid_to, today))}</p>'


def offer_card(site: Site, o: Offer, today: date, warn: list, page_path: str, link_bank=True) -> str:
    """Value-first compact card (redesign r1): who, the money line, one row of condition chips, the dated check
    with its source, then actions. Limits, the quote and "Cite this" sit one tap away in a native <details>."""
    base = site.base
    chips = "".join(f'<li class="{c}"{a}>{icon("check") if "today-ok" in c else ""}{E(t)}</li>'
                    for c, t, a in card_chips(o, today))
    code = ""
    if o.code and re.fullmatch(r"[A-Za-z0-9-]{1,32}", o.code):
        code = (f'<button class="code" type="button" data-copy="{E(o.code)}">'
                f'<span class="code-l">Code</span><code>{E(o.code)}</code>'
                f'<span class="code-a">{icon("copy")}<span class="cl" aria-live="polite">Copy</span></span></button>')
    q = quote_for(o)
    quote = (f'<blockquote class="o-quote"><p>“{E(q)}”</p><cite>{ext(o.source_url, E(domain(o.source_url)))}'
             f'</cite></blockquote>') if q else ""
    extra = "".join(f'<li>{ext(u, "More terms: " + E(domain(u)))}</li>' for u in o.terms_urls[1:])
    tl = tickets_line(o)
    ends = (f'<li data-end="{o.valid_to.isoformat()}">{E(ends_text(o.valid_to, today))}</li>' if o.valid_to else "")
    lines = (f'<li class="o-tix">{E(tl)}</li>' if tl else "") + "".join(
        f"<li>{E(t)}</li>" for t in terms_lines(o, warn) if not (o.valid_to and t == f"Ends {fmt_day(o.valid_to)}")) + ends
    seats = (f'<span class="seats" aria-hidden="true">{SEAT.format(x="")}{SEAT.format(x=" seat-lit")}</span>'
             if what(o).startswith("2nd") else "")
    typ = {"card": "card", "membership": "membership", "upi": "upi", "wallet": "upi", "platform": "direct",
           "chain": "direct"}.get(o.category, o.category)
    app = o.platform if o.platform in ("bms", "district") else "cinema"
    bank = bank_id(o.issuer) if o.is_bank else "none"
    name, full = E(who(o)), ""
    if o.variants_scope == "listed" and len(o.variants) > 2:
        # a long multi-card list (RBL names up to 6) shows 2 and a count; the full list is read aloud, searchable and in Details
        short_ = f"{o.issuer} {' / '.join(v.title() if v.islower() else v for v in o.variants[:2])} + {len(o.variants) - 2} more"
        name, full = f'<span aria-hidden="true">{E(short_)}</span>', f'<span class="sr">{E(who(o))}</span>'
    if link_bank and o.is_bank:
        name = f'<a href="/bank/{o.slug}/">{name}{full}</a>'
        full = ""
    by = checked_by(o, site.cfg)
    ck_short = f"Offer Intelligence · checked {fmt_dm(o.checked_at.astimezone(IST).date())}"
    date_s = fmt_day(o.checked_at.astimezone(IST).date())
    url = f"{base}{page_path}#{o.id}"
    line = f"{who(o)} on {where(o)}: {what(o)}, {cap(o)}"
    cite = f"{line}, per {domain(o.source_url)}, checked by {by} {date_s} ({url.replace('https://', '')})"
    share = f"{line}. {key_condition(o, today)}.{until_text(o, today)} Checked by {by} {date_s} from {domain(o.source_url)} → {url}"
    wa = "https://wa.me/?text=" + quote_url(share)
    days_attr = "any" if "any" in o.days else " ".join(day_keys(o))
    mono = monogram(bank, o.issuer) if o.is_bank else f'<span class="mono mt9" aria-hidden="true">{icon("pass" if o.category == "membership" else "card")}</span>'
    return f'''<article class="offer" id="{E(o.id)}" data-type="{typ}" data-app="{app}" data-bank="{bank}" data-days="{days_attr}"{fresh_attrs(o)}>
<p class="o-stale" hidden></p>
<h3 class="o-head">{mono}<span class="o-who">{name}</span>{full}</h3>
<p class="o-value">{seats}<span class="o-big">{E(what(o))}</span><span class="o-cap">{E(cap(o))}</span><span class="o-app">{E(where(o).split(" · ")[0])}</span></p>
<ul class="o-chips" aria-label="Conditions">{chips}</ul>
{code}
<p class="o-foot"><span class="chk">{icon("check")}<span class="ck-l">Checked by {E(by)} · <span class="nw">{E(fmt_stamp(o.checked_at))}</span></span><span class="ck-s" aria-hidden="true">{E(ck_short)}</span></span><span class="dotsep" aria-hidden="true">·</span>{ext(o.source_url, E(domain(o.source_url)) + icon("out"), cls="src", sr="official terms")}</p>
<div class="o-act"><details class="o-terms"><summary>Details</summary><ul class="o-more">{lines}{extra}</ul>{quote}
<button class="cite" type="button" data-copy="{E(cite)}"><span class="cite-t">Cite this: {E(cite)}</span><span class="cl">Copy</span></button></details>
<a class="o-page" href="{offer_path(o.id)}">Terms &amp; history</a>
{ext(wa, icon("share") + WA_LABEL, cls="share")}{share_button(share.rsplit(" → ", 1)[0], url)}</div>
</article>'''


def quote_url(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def fresh_attrs(o: Offer) -> str:
    """What the freshness guard reads: when this offer was checked and when it ends."""
    return (f' data-checked="{o.checked_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"'
            f' data-valid-to="{o.valid_to.isoformat() if o.valid_to else ""}"')


NEW_TAB = '<span class="sr"> (opens in a new tab)</span>'


def ext(url: str, inner: str, cls: str = "", nofollow: bool = True, sr: str = "") -> str:
    """The ONE way to render an external link: new tab, no opener/referrer, said aloud for screen readers.
    `inner` is already-escaped HTML; `sr` adds context before "opens in a new tab"."""
    rel = ("nofollow " if nofollow else "") + "noopener noreferrer"
    c = f' class="{cls}"' if cls else ""
    note = f'<span class="sr"> ({sr}, opens in a new tab)</span>' if sr else NEW_TAB
    return f'<a{c} href="{E(url)}" target="_blank" rel="{rel}">{inner}{note}</a>'


def check_links(html_text: str, path: str, site_host: str) -> None:
    """Build-time guard: every external <a> must come from ext(); no internal <a> may open a new tab."""
    for tag in re.findall(r"<a\s[^>]*>", html_text):
        href = re.search(r'href="([^"]*)"', tag)
        if not href:
            continue
        u = urlparse(html.unescape(href.group(1)))
        is_ext = u.scheme in ("http", "https") and (u.hostname or "").removeprefix("www.") != site_host
        if is_ext and not ('target="_blank"' in tag and "noopener" in tag and "noreferrer" in tag):
            raise SystemExit(f"{path}: external link without a new tab: {tag}")
        if not is_ext and "target=" in tag:
            raise SystemExit(f"{path}: internal link opens a new tab: {tag}")


def table(rows: list[list[str]], head: list[str], caption: str, offers: list | None = None) -> str:
    th = "".join(f'<th scope="col">{h}</th>' for h in head)
    attrs = [fresh_attrs(o) for o in offers] if offers else [""] * len(rows)
    tr = "".join(f"<tr{attrs[k]}>" + "".join(f'<td data-l="{E(re.sub("<[^>]+>", "", head[i]))}"><span>{c}</span></td>' for i, c in enumerate(r)) + "</tr>"
                 for k, r in enumerate(rows))
    return f'<div class="tbl-wrap"><table class="tbl"><caption>{caption}</caption><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def facts(items) -> str:
    """What a page's lastmod hash covers: the offers' facts, not when they were last re-checked."""
    return json.dumps([{k: v for k, v in o.raw.items() if k not in ("checked_at", "checked_on", "state")} for o in items],
                      sort_keys=True, default=str)


def stamp_of(items) -> datetime:
    return min(o.checked_at for o in items)


# ---------------------------------------------------------------- spotted (decision 135)
# Leads seen on the web (news, the bank's posts, aggregators) whose terms we haven't checked. They live in their own
# labelled section and page, and never reach a verified surface: hero, day counts, Best card, bank pages, OG cards,
# beat tiles, offers.json or Offer/Dataset structured data.
SPOT_DAYS = 7
SPOT_KIND = {"card": "Card", "upi": "UPI", "wallet": "Wallet", "membership": "Membership", "platform": "App deal",
             "chain": "Cinema chain", "code": "Code", "cashback": "Cashback"}
SPOT_PLATFORM = {"bookmyshow": "BookMyShow", "bms": "BookMyShow", "district": "District", "pvr": "PVR INOX",
                 "pvrinox": "PVR INOX", "inox": "PVR INOX", "cinepolis": "Cinépolis"}
PVR_HOME = "https://www.pvrcinemas.com/"     # PVR INOX's terms forbid deep links: home page only
# Browser half of the 7-day rule: a lead past spotted_at + 7 days or its end date hides; an empty section hides.
SPOT_JS = ("(function(){var q=/[?&]fdfs_now=(\\d+)/.exec(location.search),n=q?+q[1]:Date.now(),"
           "y=new Date(n+198e5).toISOString().slice(0,10),k=0;document.querySelectorAll('.spot').forEach(function(c){"
           "var v=c.dataset.validTo;if(v&&y>v||n-Date.parse(c.dataset.spotted)>6048e5)c.hidden=true;else k++});"
           "if(!k){document.querySelectorAll('[data-spot-section]').forEach(function(s){s.hidden=true});"
           "var e=document.querySelector('[data-spot-none]');if(e)e.hidden=false}})();")


@dataclass
class Spot:
    id: str
    issuer: str
    kind: str
    platform: str
    headline: str
    quote: str
    source_url: str
    source_name: str
    source_kind: str
    spotted_at: datetime
    valid_to: date | None
    code: str | None
    near: bool = False         # decision 168: we list a checked offer from this issuer on this app; may be the same offer
    why: str = ""              # decision 168: archive only: why it left the live list ("ended 2026-11-30", "seen 12 Nov")

    @property
    def dom_id(self) -> str:
        return "spot-" + re.sub(r"[^a-z0-9-]+", "-", self.id.lower()).strip("-")

    @property
    def type(self) -> str:
        return {"card": "card", "upi": "upi", "wallet": "upi", "membership": "membership"}.get(self.kind, "direct")

    @property
    def app(self) -> str:
        return {"bookmyshow": "bms", "bms": "bms", "district": "district"}.get(self.platform, "cinema")

    @property
    def bank(self) -> str:
        return bank_id(self.issuer) if self.kind == "card" else "none"

    @property
    def is_pvr(self) -> bool:
        # the SOURCE is a PVR INOX page (their terms: home page links only); a PVR offer cited elsewhere links there
        host = (urlparse(self.source_url).hostname or "").lower()
        return any(h in host for h in ("pvrcinemas", "pvrinox", "inoxmovies"))

    @property
    def href(self) -> str:
        return PVR_HOME if self.is_pvr else self.source_url


def issuer_key(s: str) -> str:
    """"Axis", "Axis Bank" and "AXIS BANK LTD" are one issuer."""
    return re.sub(r"\b(bank|card|cards|ltd|limited|credit)\b|[^a-z0-9]", "", (s or "").lower()) or "none"


def load_block(path) -> list:
    """data/spotted-block.json: leads a person ruled out, by id or by issuer + card, each with a reason.
    Both the build and discovery honour it (a lead the web keeps advertising stays off the site)."""
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    rows = rows.get("block", []) if isinstance(rows, dict) else rows
    return [r for r in rows if isinstance(r, dict) and (r.get("id") or (r.get("issuer") and r.get("card")))]


def block_reason(rules: list, rid: str, issuer: str, text: str) -> str | None:
    words = set(re.findall(r"[a-z0-9]+", f"{rid} {text}".lower()))
    for r in rules:
        if r.get("id") and r["id"] == rid:
            return str(r.get("reason") or "ruled out by a reviewer")
        if (r.get("issuer") and r.get("card") and issuer_key(r["issuer"]) == issuer_key(issuer)
                and set(re.findall(r"[a-z0-9]+", str(r["card"]).lower())) <= words):
            return str(r.get("reason") or "ruled out by a reviewer")
    return None


def load_spotted(path, offers: list, now: datetime, block=None, archive: list | None = None) -> tuple[list, list]:
    """Read data/spotted.json. Returns (leads to show, ["id: why"] dropped). Same clock as the export.
    `block` defaults to spotted-block.json next to the spotted file. Decision 168 (owner: "lets not miss anything"):
    leads past 7 days or past their end date go to `archive` (shown collapsed on /spotted/, up to ARCHIVE_DAYS old)
    as well as `dropped`; a lead for an issuer and app we have a checked offer on stays, marked `near`."""
    path = Path(path) if path else None
    if not path or not path.exists():
        return [], []
    rules = load_block(block if block is not None else path.with_name("spotted-block.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("leads", []) if isinstance(raw, dict) else raw
    today = now.astimezone(IST).date()
    ids = {o.id for o in offers}
    pairs = {(issuer_key(o.issuer), o.platform if o.platform in ("bms", "district") else "cinema") for o in offers}
    keep, dropped, seen = [], [], set()
    for r in rows:
        rid = str(r.get("id") or "").strip()

        def drop(why):
            dropped.append(f"{rid or '?'}: {why}")
        try:
            sp = Spot(rid, str(r["issuer"]).strip(), str(r.get("kind") or "").lower(), str(r.get("platform") or "").lower(),
                      str(r["headline"]).strip(), str(r.get("quote") or "").strip(), str(r["source_url"]).strip(),
                      str(r.get("source_name") or "").strip() or "the web", str(r.get("source_kind") or ""),
                      _dt(r["spotted_at"]), _d(r.get("valid_to")), (r.get("code") or None))
        except (KeyError, TypeError, ValueError) as e:
            drop(f"unreadable ({e.__class__.__name__})")
            continue
        if not rid or rid in seen:
            drop("missing or repeated id")
            continue
        seen.add(rid)
        if urlparse(sp.source_url).scheme not in ("http", "https") or not urlparse(sp.source_url).hostname:
            drop("source is not a web link")
        elif sp.spotted_at.tzinfo is None:
            drop("spotted_at has no time zone")
        elif now - sp.spotted_at > timedelta(days=SPOT_DAYS):
            drop(f"older than {SPOT_DAYS} days (spotted {sp.spotted_at.date().isoformat()})")
            if archive is not None and now - sp.spotted_at <= timedelta(days=ARCHIVE_DAYS) and not _hidden(rules, sp):
                sp.why = f"last seen {fmt_dm(sp.spotted_at.astimezone(IST).date())}" + (
                    f", ended {fmt_dm(sp.valid_to)}" if sp.valid_to and sp.valid_to < today else "")
                archive.append(sp)
        elif sp.valid_to and sp.valid_to < today:
            drop(f"ended {sp.valid_to.isoformat()}")
            if archive is not None and not _hidden(rules, sp):
                sp.why = f"ended {fmt_dm(sp.valid_to)}"
                archive.append(sp)
        elif rid in ids:
            drop("a verified offer covers it")
        elif block_reason(rules, rid, sp.issuer, sp.headline):
            drop("blocked: " + block_reason(rules, rid, sp.issuer, sp.headline))
        elif BANNED.search(" ".join((sp.issuer, sp.headline, sp.quote, sp.source_name, sp.code or ""))):
            drop("banned wording")
        else:
            if sp.code and not re.fullmatch(r"[A-Za-z0-9-]{1,32}", sp.code):
                sp.code = None
            sp.near = (issuer_key(sp.issuer), sp.app) in pairs
            keep.append(sp)
    # decision 162: the bank's own page first, then news and blogs, aggregators last; newest first within each. The
    # home's 3 rows are then official leads whenever there are any (a months-old festival news story no longer leads).
    keep.sort(key=lambda x: (x.near, SPOT_SOURCE_RANK.get(x.source_kind, 1), -x.spotted_at.timestamp(), x.id))
    if archive is not None:
        archive.sort(key=lambda x: (-x.spotted_at.timestamp(), x.id))
    return keep, dropped


ARCHIVE_DAYS = 60   # decision 168: older leads stay findable on /spotted/ (collapsed) for 60 days after last seen


def _hidden(rules, sp) -> bool:
    """Blocked (known stale) or banned leads never reach the archive either."""
    return bool(block_reason(rules, sp.id, sp.issuer, sp.headline)
                or BANNED.search(" ".join((sp.issuer, sp.headline, sp.quote, sp.source_name, sp.code or ""))))


def near_note(sp: "Spot") -> str:
    if not sp.near:
        return ""
    plat = SPOT_PLATFORM.get(sp.platform, "this app")
    return (f'<p class="sp-near">We list a checked {E(sp.issuer)} offer on {E(plat)}. '
            f'This lead may be that offer or another one.</p>')


SPOT_SOURCE_RANK = {"official": 0, "news": 1, "blog": 1, "aggregator": 2}


SPOT_HOME = 3   # home shows the newest 3 as compact rows; the rest open with any filter (CSS only) or on /spotted/


def spot_card(sp: Spot, extra: bool = False) -> str:
    """Same layout as a checked card, visibly not one: dashed border, the 'Spotted · not verified' pill, a dashed
    'Code (unverified)', and 'Spotted on <site>' where a checked card says 'Checked by'."""
    plat = SPOT_PLATFORM.get(sp.platform, sp.platform.title() if sp.platform else "")
    chips = [x for x in (plat, "" if sp.kind == "card" else SPOT_KIND.get(sp.kind, "")) if x and x.lower() != sp.issuer.lower()]
    if len(chips) == 2 and chips[0].lower() == chips[1].lower():
        chips = chips[:1]                                             # "PVR INOX · Cinema chain" reads once
    code = ""
    if sp.code:
        code = (f'<button class="code sp-code" type="button" data-copy="{E(sp.code)}">'
                f'<span class="code-l">Code (unverified)</span><code>{E(sp.code)}</code>'
                f'<span class="code-a">{icon("copy")}<span class="cl" aria-live="polite">Copy</span></span></button>')
    quote = (f'<details class="o-terms"><summary>Quote</summary><blockquote class="sp-q"><p>“{E(sp.quote)}”</p></blockquote>'
             f'</details>') if sp.quote else ""
    link = (ext(PVR_HOME, "pvrcinemas.com" + icon("out"), cls="src", sr="PVR INOX home page")
            if sp.is_pvr else ext(sp.source_url, "Source" + icon("out"), cls="src", sr=E(sp.source_name)))
    when = fmt_day(sp.spotted_at.astimezone(IST).date())
    bid = sp.bank if sp.bank != "none" else bank_id(sp.issuer)
    return (f'<article class="spot{" sp-x" if extra else ""}" id="{sp.dom_id}" data-type="{sp.type}" data-app="{sp.app}" data-bank="{E(sp.bank)}" '
            f'data-spotted="{sp.spotted_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'data-valid-to="{sp.valid_to.isoformat() if sp.valid_to else ""}">\n'
            f'<h3 class="o-head">{monogram(bid, sp.issuer)}<span class="o-who sp-who">{E(sp.issuer)}</span>'
            f'<span class="sp-pill"><span aria-hidden="true">👀 </span>Spotted · not verified</span></h3>\n'
            f'<p class="sp-h">{E(sp.headline)}</p>\n{near_note(sp)}'
            + (f'<ul class="o-chips" aria-label="Where">{"".join(f"<li>{E(c)}</li>" for c in chips)}</ul>\n' if chips else "")
            + f'{code}\n'
            f'<p class="sp-foot"><span>Spotted on {E(sp.source_name)} · <span class="nw">{E(when)}</span></span></p>\n'
            f'<div class="o-act">{quote}{link}</div>\n</article>')


SPOT_INTRO = "We spotted these on the web. We haven't checked their terms yet, so open the source before you rely on one."


def spot_row(sp: Spot, extra: bool = False) -> str:
    """Home (decision 149): one compact row per lead (bank · claim · source), the same data attributes as a spotted card,
    so the filters, the counts and the 7-day rule behave the same. The full card, quote and code are on /spotted/."""
    link = (ext(PVR_HOME, "pvrcinemas.com", sr="PVR INOX home page") if sp.is_pvr
            else ext(sp.source_url, E(sp.source_name), sr="source"))
    plat = SPOT_PLATFORM.get(sp.platform, sp.platform.title() if sp.platform else "")
    plat_html = f'<span class="sp-plat">{E(plat)}</span> · ' if plat else ""
    code_html = f'code <code>{E(sp.code)}</code> (unverified) · ' if sp.code else ""
    return (f'<article class="spot{" sp-x" if extra else ""}" id="{sp.dom_id}" data-type="{sp.type}" data-app="{sp.app}" '
            f'data-bank="{E(sp.bank)}" data-spotted="{sp.spotted_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'data-valid-to="{sp.valid_to.isoformat() if sp.valid_to else ""}">'
            f'<p class="sp-line"><span class="sp-who">{E(sp.issuer)}</span><span class="sp-h">{E(sp.headline)}</span>'
            f'<span class="sp-src">{plat_html}{code_html}Spotted {E(fmt_dm(sp.spotted_at.astimezone(IST).date()))} · {link}</span></p></article>')


def spot_section(spots: list, home: bool, total: int | None = None) -> str:
    if not spots:
        return ""
    fold = home and len(spots) > SPOT_HOME
    more = ""
    if home:
        more = f'<p><a class="more" href="/spotted/">See all {max(total or 0, len(spots))} spotted {icon("arrow")}</a></p>'
    if home:
        return (f'<section class="wrap block spotted" id="spotted" data-spot-section aria-labelledby="h-spotted">'
                f'<div class="sec-head"><h2 id="h-spotted"><span aria-hidden="true">👀 </span>Spotted elsewhere: not yet verified</h2>'
                f'<p class="meta">{len(spots)} spotted · newest first</p></div>'
                f'<p class="sp-intro">{E(SPOT_INTRO)}</p>'
                f'<div class="sp-list sp-home">{"".join(spot_row(x, fold and i >= SPOT_HOME) for i, x in enumerate(spots))}</div>'
                f'{more}</section>')
    return (f'<section class="wrap block spotted" id="spotted" data-spot-section aria-labelledby="h-spotted">'
            f'<div class="sec-head"><h2 id="h-spotted"><span aria-hidden="true">👀 </span>Spotted elsewhere: not yet verified</h2>'
            f'<p class="meta">{len(spots)} spotted · newest first</p></div>'
            f'<p class="sp-intro">{E(SPOT_INTRO)}</p>'
            f'<div class="grid sp-grid">{"".join(spot_card(x, fold and i >= SPOT_HOME) for i, x in enumerate(spots))}</div>'
            f'{more}</section>')


def archive_section(archive: list) -> str:
    """Decision 168: leads that left the live list (past 7 days, or ended), collapsed, newest first. Not counted, not
    filterable, no share, no code button: a record of what we saw and where."""
    if not archive:
        return ""
    rows = "".join(
        f'<li class="sp-old"><span class="sp-who">{E(sp.issuer)}</span>: {E(sp.headline)} '
        f'<span class="sp-src">· {E(sp.why)} · '
        + (ext(PVR_HOME, "pvrcinemas.com", sr="PVR INOX home page") if sp.is_pvr else ext(sp.source_url, E(sp.source_name), sr="source"))
        + '</span></li>' for sp in archive)
    n = len(archive)
    return (f'<section class="wrap block" aria-labelledby="h-old"><div class="sec-head"><h2 id="h-old">Older and ended leads</h2></div>'
            f'<details class="o-terms sp-arch"><summary>Show {n} lead{"s" if n != 1 else ""} we saw earlier</summary>'
            f'<p class="cl-p">Not checked, and not current: kept so nothing we saw is lost. Each links to where we saw it.</p>'
            f'<ul class="plain">{rows}</ul></details></section>')


def page_spotted(spots: list, now: datetime, base: str, archive: list | None = None) -> Page:
    n = len(spots)
    answer = (f"<strong>{n} offer{'s' if n != 1 else ''} spotted on the web, not yet verified.</strong> Each links to where "
              f"we saw it. The offers we checked against the official terms are on the <a href=\"/\">main list</a>.")
    body = (spot_section(spots, False) + archive_section(archive or [])
            + '<section class="wrap block" data-spot-none hidden><p class="log-one">Nothing spotted in the last 7 days. '
              'See the <a href="/">checked offers</a>.</p></section>')
    key = json.dumps([[x.id, x.headline, x.quote, x.href, x.code, x.valid_to and x.valid_to.isoformat(), x.near]
                      for x in spots] + [[x.id, x.why] for x in archive or []])
    return Page("/spotted/", "Spotted movie ticket offers, not yet verified · FDFS",
                "Movie ticket offers we saw on the web but haven't checked against the terms yet. Each has its source, "
                "the date we saw it and a short quote.",
                "Spotted offers, <em>not yet verified.</em>", answer, body, [("Offers", "/"), ("Spotted", "/spotted/")],
                "Updated", now, key, noindex=n < 10, js=SPOT_JS)   # QA F3: unverified claims never become structured data


# ---------------------------------------------------------------- pages

ORDER_NOTE = "Sorted by most recent check, then soonest end date. The same rule for every app."


def home_order(o: Offer) -> tuple:
    """L4 (decision 140): the home list's one ordering rule, app-blind. Freshest evidence (the IST day it was checked)
    first, then the soonest stated end date (no end date last), then the label. ORDER_NOTE says exactly this."""
    day = o.checked_at.astimezone(IST).date() if o.checked_at else date.min
    return (-day.toordinal(), o.valid_to or date.max, who(o).lower(), o.id)


def short_card(o: Offer) -> str:
    """'HSBC Premier' for a card the terms list by name; the full label otherwise (never wider than the terms)."""
    if o.is_bank and o.variants_scope == "listed" and len(o.variants) == 1:
        return f"{o.issuer} {variant_name(o.variants[0])}"
    return who(o)


DESC_MAX = 160


def meta_desc(desc: str, n: int = DESC_MAX) -> str:
    """The meta and og description (decision 163): whole sentences up to 160 characters, so search results don't cut
    the snippet mid-word. A first sentence that alone runs long ends at a word boundary with an ellipsis. The full text
    stays in llms.txt and the page's JSON-LD."""
    desc = " ".join(desc.split())
    if len(desc) <= n:
        return desc
    out = ""
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹])", desc):
        if len(out) + len(s) + (1 if out else 0) > n:
            break
        out = f"{out} {s}" if out else s
    if out:
        return out
    cut = desc[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:(")
    return cut + "…"


def search_example(movie: list) -> str:
    """The search box's example (decision 162): built from a listed offer, so typing it always finds one. A bank, a
    day the offer allows (an every-day or no-day offer fits any day: Saturday reads naturally) and its app."""
    for o in movie:
        if not o.is_bank:
            continue
        app = {"bms": "bms", "district": "district"}.get(o.platform)
        dk = day_keys(o)
        day = dk[0] if dk else "sat"
        return " ".join(x for x in (bank_id(o.issuer), day, app) if x)
    return "sat bms"


def hero_verdict(site: Site, movie: list) -> str:
    """'5 checked movie offers · highest cap ₹750 (HSBC Premier, BookMyShow)', from the data; two lines on a phone.
    The top pick is a fresh offer only (D4); with none fresh, the line is just the count."""
    n = len(movie)
    head = f"<strong>{n} checked movie offer{'s' if n != 1 else ''}</strong>"
    fresh = [o for o in movie if freshness(o, site.now) == "fresh" and cap_num(o)]
    if not fresh:
        return head + "."
    top = max(fresh, key=lambda o: (cap_num(o), o.id))
    # the freshness guard hides this clause on a visit 7+ days after the check (it reads data-sat-hero, the hero's hook)
    return head + (f"<span data-sat-hero{fresh_attrs(top)}> · highest cap ₹{cap_num(top):,} "
                   f"({E(short_card(top))}, {E(app_name(top))})</span>")


HOME_CSS = '.sp-home{border:1.5px dashed var(--spot);border-radius:var(--r-3)}.sp-home>.spot{padding:var(--s-3) var(--s-4);border:0;border-bottom:1px dashed var(--line);border-radius:0;gap:0}.sp-home>.spot:last-of-type{border-bottom:0}.sp-line{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px var(--s-2);font-size:var(--t-sm)}.sp-home .sp-who{font-weight:700}.sp-home .sp-h{color:var(--text-2)}.sp-home .sp-src{flex-basis:100%;font-size:var(--t-xs);color:var(--text-3)}.what.what-band{padding-block:var(--s-8)}.what-band .what-in{gap:var(--s-2)}.what-band .what-h{font-size:var(--t-lg)}.what-band .what-a{margin:0;font-size:var(--t-md);color:var(--text-2)}.what-l{display:flex;flex-wrap:wrap;gap:var(--s-2) var(--s-4)}.what-l a{display:inline-flex;align-items:center;min-height:44px;font-weight:700}.find{grid-template-columns:minmax(0,1fr) auto;align-items:center}.find .fbtn{min-height:48px}.changes-band{padding-block:0 var(--s-8)}.band-h{font:700 var(--t-xs)/1.3 var(--font);letter-spacing:.08em;text-transform:uppercase;color:var(--text-3);margin-bottom:var(--s-2)}@media (max-width:519px){.hero:not(.hero-sm) .s-a{font-size:1rem}}.js .fbtn{display:inline-flex}.js .filters>.frow{flex:1 1 0}@media (min-width:720px){.fsheet[open]{inset:0;margin:auto;max-width:560px;height:fit-content;max-height:85vh;border-radius:20px}}.fsheet .wallet{padding-bottom:var(--s-2)}.fsheet .bybank{margin:var(--s-2) 0 0}' + (   # decision 149: home-only rules stay off the shared sheet
    # decision 162: a shorter home hero, so the first offer starts on the first screen (phone and desktop)
    '.hero:not(.hero-sm){padding-block:var(--s-5) var(--s-4);gap:var(--s-4)}.hero:not(.hero-sm) .stage{padding:14px 12px}'
    '.hero:not(.hero-sm) .ticket{padding:12px 16px 14px}.hero:not(.hero-sm) .s-a{margin-top:12px;padding-top:10px}'
    '.hero:not(.hero-sm) h1{font-size:clamp(1.9rem,4.4vw,3.1rem);max-width:18ch}#offers.block{padding-top:var(--s-5)}'
    '@media (min-width:900px){.hero:not(.hero-sm){padding-block:var(--s-6) var(--s-5)}.hero:not(.hero-sm) .stage{padding:18px 20px}}'
    '@media (max-width:519px){.hero:not(.hero-sm) .beats{display:none}.hero:not(.hero-sm) h1{font-size:min(8vw,1.9rem)}}')


def page_home(site: Site, offers: list[Offer], changes: list, today: date, warn: list, spots: list | None = None,
              spot_total: int | None = None) -> Page:
    spots = spots or []
    movie = sorted([o for o in offers if o.is_movie], key=home_order)
    events = [o for o in offers if not o.is_movie]
    stamp = stamp_of(offers) if offers else site.now
    d = fmt_day(stamp.astimezone(IST).date())
    caps = sorted({cap_num(o) for o in movie if cap_num(o)})
    if movie:
        rng = f"₹{caps[0]:,}–₹{caps[-1]:,}" if len(caps) > 1 else f"₹{caps[0]:,}"
        answer = hero_verdict(site, movie)       # owner refresh (decision 149): one verdict line, the stamp above it
    else:
        answer = f"No movie ticket offer passes our checks on {d}. We show only offers we could verify on the official terms."
    # which-day strip: the next 7 days from today (IST). The big number is the DATE; the caption is how many offers
    # you'll see after tapping it: offers bookable that weekday PLUS those whose terms name no days (always shown).
    nodays = sum(1 for o in movie if not day_keys(o) and "any" not in o.days)
    counts = {k: sum(1 for o in movie if "any" in o.days or k in day_keys(o) or (not day_keys(o) and "any" not in o.days))
              for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    cells = ""
    for i in range(7):
        dd = today + timedelta(days=i)
        k = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[dd.weekday()]
        n = counts[k]
        cap_ = "No offers" if n == 0 else f"{n} offer{'s' if n != 1 else ''}"
        # disabled until the page script runs: without JS this is a static strip, never a fake button
        cells += (f'<button type="button" class="day{" none" if n == 0 else ""}" data-day="{k}" data-date="{dd.isoformat()}" '
                  f'aria-pressed="false" aria-label="{DAY[k][:3]} {dd.day} {dd:%b}, {cap_ if n else "no offers"}" disabled>'
                  f'<span class="d">{DAY[k][:3]}</span><span class="c">{dd.day}</span><span class="m">{dd:%b}</span>'
                  f'<span class="n">{cap_}</span></button>')
    days_html = (f'<div class="days-wrap" data-days-filter data-counts=\'{json.dumps(counts, separators=(",", ":"))}\'>'
                 f'<p class="days-h" id="days-h">Which day are you booking?</p>'
                 f'<div class="days" role="group" aria-labelledby="days-h">{cells}</div>'
                 f'<button type="button" class="day-all" data-day="" aria-pressed="false" disabled>All days</button>'
                 + (f'<p class="days-n">Counts include {nodays} offer{"s" if nodays != 1 else ""} that don\'t name days: '
                    f'marked "Days not stated". Check their terms.</p>' if nodays else "")
                 + f'<p class="days-cal"><a href="/calendar/">Plan the week by day {icon("cal")}</a></p>'   # P3, decision 153
                 + "</div>") if movie else ""
    # filters: chips with 0 offers (checked or spotted) aren't built (no promise without an offer). With JS, counts go
    # live and a chip that the other filters empty is greyed, never hidden. Without JS these radios filter by CSS.
    bank_names = {}
    for o in movie:
        if o.is_bank:
            bank_names.setdefault(bank_id(o.issuer), bank_label(bank_id(o.issuer), site.bank_name(o.issuer)))
    for x in spots:
        if x.bank != "none":
            bank_names.setdefault(x.bank, bank_label(x.bank, re.sub(r"<[^>]+>", "", x.issuer)))
    groups = [("app", "Book on", [("all", "All"), ("bms", "BookMyShow"), ("district", "District"), ("cinema", "Cinemas")]),
              ("type", "Type", [("all", "All"), ("card", "Cards"), ("upi", "UPI & wallets"), ("direct", "Direct deals"),
                                ("membership", "Memberships")]),
              ("bank", "I have", [("all", "Any card")] + sorted(bank_names.items(), key=lambda kv: kv[1].lower()))]

    def attr(o, g):
        typ = {"card": "card", "membership": "membership", "upi": "upi", "wallet": "upi"}.get(o.category, "direct")
        return {"type": typ, "app": o.platform if o.platform in ("bms", "district") else "cinema",
                "bank": bank_id(o.issuer) if o.is_bank else "none"}[g]
    rows, css = [], []
    for g, legend, vals in groups:
        chips = ""
        for v, label in vals:
            n = len(movie) if v == "all" else sum(1 for o in movie if attr(o, g) == v)
            ns = 0 if v == "all" else sum(1 for x in spots if getattr(x, g) == v)   # spotted leads: a separate count
            if n == 0 and ns == 0 and v != "all":
                continue
            chips += (f'<input class="sr" type="radio" name="{g}" id="{g}-{v}" value="{v}"{" checked" if v == "all" else ""}>'
                      f'<label class="chip" for="{g}-{v}">{E(label)}<span class="n">{n}</span>'
                      + (f'<span class="ns">+ {ns} spotted</span>' if ns else "") + '</label>')
            if v != "all":
                css.append(f'body:has(#{g}-{v}:checked) .offer:not([data-{g}="{v}"])')
                if spots:
                    css.append(f'body:has(#{g}-{v}:checked) .spot:not([data-{g}="{v}"])')
        rows.append(f'<fieldset class="frow{" tabs" if g == "app" else ""}"><legend>{legend}</legend><div class="chips">{chips}</div></fieldset>'
                    + (f'<p class="order-note">{ORDER_NOTE}</p>' if g == "app" else ""))
    filter_css = (",".join(css) + "{display:none}" if css else "") + \
        "body:has(.filters input:not([value=\"all\"]):checked) .also{display:none}"
    # search, "My cards" and the applied bar only appear with JS (a control that can't work is never shown)
    eg = search_example(movie)
    find = (f'<div class="find" data-find hidden><div class="q-wrap" data-eg="{E(eg)}"><label class="sr" for="q">Search offers by bank, card, app or day</label>'
            f'{icon("search")}<input id="q" type="search" autocomplete="off" '
            f'spellcheck="false" enterkeyhint="search" aria-describedby="q-h"></div>'
            f'<p class="sr" id="q-h">Type a bank, card, app or day, for example {E(eg)}. Results update as you type.</p>'
            f'<button type="button" class="fbtn" data-fbtn aria-haspopup="dialog" aria-controls="fd">Filters<span class="n" data-fn hidden></span></button>'
            '</div>') if movie or spots else ""
    applied = ('<div class="applied" data-applied hidden><p class="ap-in"><span class="ap-l" data-ap-l>Showing:</span>'
               '<span class="ap-c" data-ap-c></span><button type="button" class="ap-x" data-clear>Clear all</button>'
               f'<button type="button" class="ap-s" data-share-view>{icon("share")}Share this list</button></p></div>')
    bybank = " · ".join(f'<a href="/bank/{s}/">{E(site.bank_name(n))} ({sum(1 for o in movie if o.is_bank and o.slug == s)})</a>'
                        for s, n in site.banks if any(o.is_bank and o.slug == s for o in movie))
    byapp = " · ".join(f'<a href="{pth}">{E(n)} ({sum(1 for o in movie if app_key(o.platform) and hub_path(app_key(o.platform)) == pth)})</a>'
                       for pth, n in site.apps) + (f' · <a href="{site.week}">This week</a>' if site.week else "")
    # SHEET: only search, the app tabs and the day strip stay in view (decision 149); My cards, Type, I have and the
    # by-bank / by-app links live in this one sheet behind "Filters (n)". Without JS the sheet is static (all visible).
    links_html = ((f'<p class="bybank"><span>Movie offers by bank:</span> {bybank}</p>' if bybank else "")
                  + (f'<p class="bybank byapp"><span>By app:</span> {byapp}</p>' if byapp else ""))
    sheet = (f'<dialog class="fsheet" id="fd" aria-labelledby="fd-h"><p class="sheet-h" id="fd-h">Filters</p>'
             + ('<div class="wallet" data-wallet></div>' if movie or spots else "") + f'{"".join(rows[1:])}{links_html}'
             f'<div class="sheet-f"><button type="button" class="ap-x" data-clear>Clear all</button>'
             f'<button type="button" class="go" data-fclose>Show <span data-fcount>{len(movie)}</span> offers</button></div></dialog>')
    cards = "\n".join(offer_card(site, o, today, warn, "/") for o in movie)
    ev = ""
    for o in events:
        # not a movie offer: a one-line note under the list, never a tile in the offers grid (lead review, r1)
        ev += (f'<aside class="also" aria-label="Live events offer"><p><span class="also-l">Live events:</span> '
               f'{E(who(o))} · {E(where(o).split(" · ")[0])}: {E(what(o))}, {E(cap(o))} on live event tickets'
               f'{E(", ends " + fmt_dm(o.valid_to)) if o.valid_to else ""} · '
               f'{ext(o.source_url, "terms" + icon("out"))} · <a href="{offer_path(o.id)}">details</a></p></aside>')
    if changes and all(c["type"] == "first_check" for c in changes):
        first = changes[-1]["date"]
        latest = (f'<p class="log-one">{len(changes)} offers first checked on {E(fmt_day(_d(first)))} · '
                  f'<a href="/changes/">All changes {icon("arrow")}</a></p>')
    else:
        latest = ('<ol class="log">' + "".join(
            f'<li class="log-i"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span><p>{E(c["text"])}</p></li>'
            for c in changes[:4]) + f'</ol><p><a class="more" href="/changes/">All changes {icon("arrow")}</a></p>') if changes else \
            '<p class="log-one">No changes recorded yet.</p>'
    body = f'''<section class="wrap block" id="offers" aria-labelledby="h-offers">
<div class="sec-head"><h2 id="h-offers">Offers that pass our checks</h2><p class="meta" role="status" data-status>Showing <span data-count>{len(movie)}</span> of {len(movie)}</p></div>
<p class="newn" data-new hidden></p>
{find}
<form class="filters" id="ff" data-filter aria-label="Filter offers" onsubmit="return false">{rows[0]}{sheet}</form>
{days_html}
{applied}
<div class="grid">{cards}</div>
<div class="empty" hidden><p class="empty-t">No checked offer fits these filters.</p>
<p class="why" data-why hidden></p>
<p>We list only offers whose official terms we could read and re-confirm. <a href="/how-we-check/">How we check</a></p>
<button class="reset" type="reset" form="ff">Show all offers</button></div>
</section>
{f'<section class="wrap block" id="events" aria-labelledby="h-ev"><div class="sec-head"><h2 id="h-ev">Concerts and live events</h2></div><p class="ev-i">Checked against the official terms like the movie offers. These work on live event tickets, not movies.</p>{ev}</section>' if ev else ""}
{spot_section(spots, True, spot_total)}
<section class="wrap block changes-band" aria-labelledby="h-changes"><h2 id="h-changes" class="band-h">Latest changes</h2>{latest}</section>
<section class="what what-band" id="what" aria-labelledby="h-what"><div class="wrap what-in">
<h2 id="h-what" class="what-h"><span class="sr">What is FDFS? </span>Film · Deals · Friends · Seats</h2>
<p class="what-a">The four things every movie plan comes down to. We start with the deals, each checked against the official terms.</p>
<p class="what-l"><a href="/how-we-check/">How we check</a><a href="/about/">About FDFS</a></p>
</div></section>'''
    hero = ('<p class="beats" aria-label="FDFS: Film, Deals, Friends, Seats"><span>Film</span><i></i><span>Deals</span><i></i>'
            '<span>Friends</span><i></i><span>Seats</span></p>')
    apps = " & ".join(sorted({app_name(o) for o in movie}, key=lambda a: a != "BookMyShow")) or "BookMyShow & District"
    dm = fmt_dm(stamp.astimezone(IST).date())
    title = fit_title([f"Movie ticket offers on {apps}, checked {dm}", f"Movie ticket offers on {apps} ({dm})",
                       "Movie ticket offers, checked"])
    names = []
    for o in movie:
        n = site.bank_name(o.issuer) if o.is_bank else who(o)
        if n not in names:
            names.append(n)
    desc = (f"{len(movie)} movie ticket offers from {join_and(names)}, each checked against the official terms on {d}. "
            f"Caps, days, codes and the exact clause." if movie else f"Movie ticket offers checked against the official terms on {d}.")
    key = facts(movie + events) + json.dumps([x.id for x in spots] + [spot_total]) + json.dumps(changes[:4], sort_keys=True) 
    og = og_hub("home", "Movie ticket offers", movie)
    return Page("/", title, desc, "Movie ticket offers, checked at the <em>source.</em>", answer, body,
                [("Offers", "/")], "Checked", stamp, key, hero=hero, css=HOME_CSS + filter_css, og=og,
                js=(SPOT_JS if spots else "") + (feed_js(movie, site.meta) if movie or spots else "") + (NEW_JS if movie else "")
                + (home_js() if movie or spots else "") + ("\n" + PLAN.page_js(movie, site.plan_gone) if movie else ""))


def site_card_name(site: "Site", path: str) -> str:
    return next((nm for p, nm, _ in site.cards if p == path), "")


def page_bank(site: Site, slug: str, offers: list[Offer], changes: list, today: date, warn: list) -> Page:
    name = site.bank_name(offers[0].issuer)
    short = offers[0].issuer
    movie = sorted([o for o in offers if o.is_movie], key=lambda o: (-cap_num(o), o.id))
    events = [o for o in offers if not o.is_movie]
    apps_l = sorted({app_name(o) for o in movie}, key=lambda a: a != "BookMyShow")
    stamp = stamp_of(offers)
    d, dm = fmt_day(stamp.astimezone(IST).date()), fmt_dm(stamp.astimezone(IST).date())
    path = f"/bank/{slug}/"
    if movie:
        best = movie[0]
        doms = join_and(sorted({domain(o.source_url) for o in movie}))
        parts = []
        for o in movie:
            g = gate_short(o, today)
            extra = f" ({g})" if g else (f" ({times(o.monthly_limit).lower()})" if o.monthly_limit else "")
            v = "get" if who(o).endswith("cards") else "gets"
            verb = f"{v} the 2nd ticket free" if what(o) == "2nd ticket free" else f"{v} {what(o)}"
            parts.append(f"{mid(who(o)) if parts else who(o)} {verb}{cap_tail(o)}{extra}")
        ends = sorted({o.valid_to for o in movie if o.valid_to})
        if len(ends) == 1 and all(o.valid_to for o in movie):
            end = f" {'Both end' if len(movie) == 2 else 'All end' if len(movie) > 2 else 'It ends'} {fmt_day(ends[0])}."
        elif not ends:
            end = " No end date is stated."
        else:
            end = ""
        answer = (f"<strong>Yes.</strong> On {d}, {E(doms)} list{'s' if ' and ' not in doms else ''} "
                  f"{len(movie)} movie offer{'s' if len(movie) > 1 else ''} on {E(' and '.join(apps_l))}: {E('; '.join(parts))}.{E(end)}")
        apps_t = " & ".join(apps_l) + (" offers" if len(apps_l) > 1 else " offer")
        dated = [f"{name} {apps_t}: {what(best)} {cap(best)} ({dm})"]
        # decision 172: name the card type people search for ("HDFC credit card BookMyShow offer") when every
        # movie offer on the page is on that one card type; the cap drops out of the title before the card type does
        kinds = {o.instrument for o in movie}
        ctype = f" {next(iter(kinds))} card" if len(kinds) == 1 and kinds <= {"credit", "debit"} else ""
        # decision 174: an issuer whose name already ends in "Card" ("SBI Card") reads "SBI credit card", not
        # "SBI Card credit card"; and the benefit stays in the title without its cap before the title drops to the bare name
        lead = name[:-5] if ctype and name.endswith(" Card") else name
        plain = ([f"{lead}{ctype} {apps_t}: {what(best)} {cap(best)}", f"{lead}{ctype} {apps_t}: {what(best)}"] if ctype else []) \
            + [f"{name} {apps_t}: {what(best)} {cap(best)}", f"{name} {apps_t}: {what(best)}", f"{name} {apps_t}"]
        title = fit_title(dated + plain)
        h1 = f"Does {E(short)} have a {E(' or '.join(apps_l))} offer?"
    else:
        answer = f"<strong>No movie offer from {E(name)} passes our checks on {d}.</strong> It has {len(events)} offer for live events."
        title = fit_title([f"{name} BookMyShow offers: none for movies ({dm})", f"{name} movie offers"])
        h1 = f"Does {E(short)} have a movie ticket offer?"
    # quotable description, platforms deduped
    def day_rule(o):
        g = gate_short(o, today)
        return f" ({g})" if g and g.startswith("when you book") else ""
    bits = [f"{who(o).replace(short + ' ', '', 1) if who(o).startswith(short + ' ') else who(o)}: {what(o)}{cap_tail(o)}"
            + day_rule(o).replace("when you book", "book") + (f" (code {o.code})" if o.code else "") for o in movie[:3]]
    gates = {spend_gate(o.quota_note) for o in movie}
    common = f" {'Both need' if len(movie) == 2 else 'All need'} {next(iter(gates))[6:]}." if len(gates) == 1 and None not in gates and len(movie) > 1 else ""
    # decision 161: say "buy 1 get 1" (the words people search) only when every movie offer here is a 2nd-ticket-free offer
    b1g1 = "buy 1 get 1 " if movie and all(what(o) == "2nd ticket free" for o in movie) else ""
    # decision 174: "movie ticket offer", the words in the questions people ask ("SBI card movie ticket offer"); only movie
    # offers are counted here, so the words are true
    desc = (f"Yes: {len(movie)} {name} {b1g1}movie ticket offer{'s' if len(movie) > 1 else ''} on {join_and(apps_l)}, checked {d}. "
            + ". ".join(bits) + "." + common) if movie else f"{name}: no movie ticket offer passes our checks on {d}."
    rows = [[f'<a href="#{E(o.id)}">{E(who(o))}</a>', E(where(o)), E(what(o)), E(cap(o)), E(key_condition(o, today)),
             E(fmt_day(o.valid_to)) if o.valid_to else "Not stated",
             ext(o.source_url, E(domain(o.source_url)))] for o in movie + events]
    tbl = table(rows, ["Card", "Where", "Benefit", "Cap", "Key condition", "Ends", "Terms"], f"{E(name)} offers, checked {fmt_stamp(stamp)}",
                movie + events)
    which = []
    for o in movie + events:
        if o.variants_scope == "unstated":
            s = f"{where(o)}: select {short} credit cards. The terms don't list which."
        elif o.variants and o.variants_scope == "listed":
            s = f"{where(o)}: listed in the terms: {', '.join(o.variants)}."
        else:
            s = f"{where(o)}: all {short} {'debit' if o.instrument == 'debit' else 'credit'} cards, per the terms."
        if any(c.startswith("bins:") for c in o.conditions):
            s += " Only cards whose first digits (BIN) are listed in the terms."
        cl = [f'<a href="{card_path_of(o, v)}">{E(site_card_name(site, card_path_of(o, v)))}</a>' for v in o.variants
              if o.variants_scope == "listed" and o.is_movie and site_card_name(site, card_path_of(o, v))]
        which.append(E(s) + (f" Card page: {', '.join(cl)}." if cl else ""))
    others = (f"Other {short} cards: not in these terms."
              if all(o.variants_scope == "listed" for o in offers) else "")
    which_html = "".join(f"<li>{s}</li>" for s in which) + (f"<li>{E(others)}</li>" if others else "")
    cards = "\n".join(offer_card(site, o, today, warn, path, link_bank=False) for o in movie + events)
    hist = [c for c in changes if c.get("issuer") == short]
    hist_html = "".join(f'<li class="log-i"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span><p>{E(c["text"])}</p></li>'
                        for c in hist) or '<li class="log-i"><p>No changes recorded yet.</p></li>'
    related = "".join(f'<li><a href="/bank/{s}/">{E(site.bank_name(n))} offers</a></li>' for s, n in site.banks if s != slug) + \
        "".join(f'<li><a href="{pth}">{E(n)} offers</a></li>' for pth, n in site.apps) + \
        "".join(f'<li><a href="/bank/{slug}/{APPS[k][0]}/">{E(short)} on {E(APPS[k][1])}</a></li>' for k in site.bank_apps.get(slug, []))
    share_t = (f"{name} movie offers: " + "; ".join(f"{who(o)} on {where(o).split(' · ')[0]}, {what(o)} {cap(o)}"
                                                    + day_rule(o).replace("when you book", "book") for o in movie[:3])
               + f". Checked {d} from the bank's terms.") if movie else f"{name} offers, checked {d}."
    body = share_row(share_t, site.base + path) + f'''<section class="wrap block" aria-labelledby="h-t"><div class="sec-head"><h2 id="h-t">Conditions at a glance</h2></div>{tbl}</section>
<section class="wrap block" aria-labelledby="h-w"><div class="sec-head"><h2 id="h-w">Which {E(short)} cards?</h2></div><ul class="plain">{which_html}</ul></section>
<section class="wrap block" aria-labelledby="h-o"><div class="sec-head"><h2 id="h-o">Each offer, with its terms</h2></div><div class="grid">{cards}</div></section>
<section class="wrap block" aria-labelledby="h-h"><div class="sec-head"><h2 id="h-h">History</h2><a class="more" href="/changes/">All changes {icon("arrow")}</a></div><ol class="log">{hist_html}</ol></section>
{f'<section class="wrap block" aria-labelledby="h-r"><div class="sec-head"><h2 id="h-r">More offers</h2></div><ul class="links">{related}</ul></section>' if related else ""}'''
    key = facts(offers) + json.dumps(hist, sort_keys=True) + related + "".join(key_condition(o, today) for o in offers)
    og = og_hub(f"bank-{slug}", f"{short} movie offers", movie)
    p = Page(path, title, desc, h1, answer, body, [("Offers", "/"), (f"{name} offers", path)], "Checked", stamp, key, og=og)
    p.title_options = (dated, plain) if movie else None
    return p


BEST_ORDER = ("Grouped by benefit type. Within a group: highest stated cap first, then the card name. "
              "The app is never part of the order.")


def best_verdict(group: list) -> str:
    """One line per benefit group, from the data: how many, the cap range as written, and the highest cap's card."""
    n = len(group)
    caps = sorted({cap_num(o) for o in group if cap_num(o)})
    apps = join_and(sorted({app_name(o) for o in group}))
    top = max(group, key=lambda o: (cap_num(o), o.id))
    rng = (f"Stated caps run from ₹{caps[0]:,} to ₹{caps[-1]:,} (per ticket or per month, as each term says). " if len(caps) > 1
           else f"The stated cap is ₹{caps[0]:,}. " if caps else "")
    return (f"{n} checked offer{'s' if n != 1 else ''} on {apps}. {rng}"
            + (f"Highest cap: {who(top)}, {cap(top)}." if caps and n > 1 else "")).strip()


def page_best(site: Site, offers: list[Offer], today: date) -> Page | None:
    movie = [o for o in offers if o.is_movie and freshness(o, site.now) == "fresh"]   # D4: needs_recheck never in Best
    if not movie:
        return None
    stamp = stamp_of(movie)
    d, dm = fmt_day(stamp.astimezone(IST).date()), fmt_dm(stamp.astimezone(IST).date())
    sections = ""
    head = ["Card or pass", "Where", "Benefit", "Cap", "Key condition", "Ends", "Terms"]

    card_of: dict = {}
    for pth, _, b in site.cards:
        for o in movie:
            if o.is_bank and o.slug == b and o.variants_scope == "listed" and any(pth == card_path_of(o, v) for v in o.variants):
                card_of.setdefault(o.id, pth)

    def row(o):
        href = card_of.get(o.id) or f"/bank/{o.slug}/#{o.id}"
        return [f'<a href="{E(href)}">{E(who(o))}</a>' if o.is_bank else E(who(o)), E(where(o)), E(what(o)),
                E(cap(o)), E(key_condition(o, today)), E(fmt_day(o.valid_to)) if o.valid_to else "Not stated",
                ext(o.source_url, E(domain(o.source_url)))]
    cards = sorted([o for o in movie if o.category != "membership"], key=lambda o: (-cap_num(o), o.id))
    groups: dict = {}
    for o in cards:                                   # decision 145: one group per benefit type, apps side by side
        groups.setdefault(KIND_GROUP.get(o.kind, o.kind.title()), []).append(o)
    order = sorted(groups, key=lambda k: (list(KIND_GROUP.values()).index(k) if k in KIND_GROUP.values() else 9, k))
    sections += (f'<section class="wrap"><p class="order-note">{E(BEST_ORDER)} '
                 f'<a href="/how-we-check/">How we check</a></p></section>')
    for kind in order:
        h = "2nd ticket free" if kind == KIND_GROUP["bogo"] else kind
        hid = "h-" + re.sub("[^a-z0-9]+", "-", h.lower()).strip("-")
        sections += (f'<section class="wrap block" aria-labelledby="{hid}">'
                     f'<div class="sec-head"><h2 id="{hid}">{E(h)}</h2></div><p class="verdict">{E(best_verdict(groups[kind]))}</p>'
                     f'{table([row(o) for o in groups[kind]], head, E(h) + ", highest cap first", groups[kind])}</section>')
    mem = [o for o in movie if o.category == "membership"]
    if mem:
        sections += (f'<section class="wrap block" aria-labelledby="h-mem"><div class="sec-head"><h2 id="h-mem">Paid memberships</h2></div>'
                     f'{table([row(o) for o in mem], head, "Paid memberships", mem)}</section>')
    by_app = {}
    for o in cards:
        by_app.setdefault(app_name(o), o)
    parts = []
    for app in sorted(by_app, key=lambda a: a != "BookMyShow"):
        o = by_app[app]
        g = gate_short(o, today)
        parts.append(f"{who(o)} on {app} ({what(o)}, {cap(o)}{'; ' + g if g else ''})")
    answer = (f"<strong>It depends on the app.</strong> Of the {len(movie)} movie offers we could confirm from official terms on {d}, "
              f"the highest caps are {E(join_and(parts))}." if parts else
              f"Of the {len(movie)} movie offers we could confirm from official terms on {d}, only a paid membership passes our checks.")
    listed = {o.issuer.lower() for o in movie}
    missing = [b for b in (site.cfg.get("not_yet_listed") or []) if b.lower() not in listed]
    gated = [o for o in movie if gate(o, today)]
    kinds = {}
    for o in gated:
        g = gate(o, today)
        k = "a spend gate" if g.startswith("Needs ₹") else \
            f"a {g.split()[3].rstrip('.,(')}-only booking" if g.startswith("Book on") else \
            "a paid pass" if g.startswith("Paid pass") else "a minimum ticket count"
        kinds[k] = kinds.get(k, 0) + 1
    no_end = sum(1 for o in movie if not o.valid_to)
    stat = (f"{len(gated)} of {len(movie)} movie offers checked on {d} need more than the card: "
            + join_and([f"{k} ({n})" for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))]) + f". {no_end} don't state an end date.") if gated else ""
    byapp = " · ".join(f'<a href="{pth}">{E(n)} offers</a>' for pth, n in site.apps)
    body = (f'<section class="wrap block"><p class="stat">{E(stat)}</p></section>' if stat else "") + sections + \
        (f'<section class="wrap block"><p class="bybank"><span>Every offer by app:</span> {byapp}</p></section>' if byapp else "") + \
        (f'<section class="wrap block"><p class="notyet"><strong>Not on this list yet:</strong> {E(", ".join(missing))} and others. '
         f'We add a card only once its official terms pass our checks.</p></section>' if missing else "") + \
        '''<section class="wrap block"><div class="prose"><h2>How this list works</h2>
<p>Every row is an offer we read on the bank's own terms page or the app's published policy page, then re-read to confirm. Rows are grouped by benefit type and sorted by the cap, whatever the app. Best card depends on where and when you book: here's every checked card offer, grouped by benefit type. We don't rank them; pick the one that fits. A higher cap only helps if your ticket costs more than the cap, and every offer has its own days and limits.</p>
<p>We have no affiliate links and no paid placements. <a href="/disclosures/">Disclosures</a> · <a href="/how-we-check/">How we check</a></p></div></section>'''
    key = facts(movie) + "".join(key_condition(o, today) for o in movie) + ",".join(missing) + BEST_ORDER   # grouping is content
    title = fit_title([f"Best credit card for movie tickets, by benefit (checked {d})",
                       f"Best credit card for movie tickets, by benefit ({d})",
                       f"Best credit card for movie tickets, by benefit ({dm})", "Best credit card for movie tickets"])
    top = by_app.get("BookMyShow") or (cards[0] if cards else movie[0])
    og = og_hub("best-card", "Best card for movie tickets", movie)
    desc = (f"Of {len(movie)} movie ticket offers confirmed from official terms on {d}: caps, days, spend gates and the exact "
            f"terms, by benefit type. Not yet listed: {', '.join(missing)}." if missing else
            f"Of {len(movie)} movie ticket offers confirmed from official terms on {d}: caps, days and the exact terms, by benefit type.")
    return Page("/best-card-for-movie-tickets/", title, desc, "Which credit card is best for movie tickets?", answer, body,
                [("Offers", "/"), ("Best credit card for movie tickets", "/best-card-for-movie-tickets/")], "Checked", stamp,
                key, og=og)


# ---------------------------------------------------------------- SEO page plan (redesign r1, section C)
# Real data only: an app hub needs >= 1 offer that passes our checks on that app; a bank x app page only exists when
# the bank has checked offers on 2+ apps (with one app, the bank page already is that page); a weekly digest only for
# a week with >= 1 offer to list. No Product/Offer markup on bank discounts, no FAQPage padding.
APPS = {"bms": ("bookmyshow", "BookMyShow"), "district": ("district", "District"), "pvr": ("pvr-inox", "PVR INOX"),
        "cinepolis": ("cinepolis", "Cinépolis")}


def app_key(platform: str) -> str | None:
    p = (platform or "").lower()
    if p in ("bms", "bookmyshow"):
        return "bms"
    if p == "district":
        return "district"
    if "pvr" in p or "inox" in p:
        return "pvr"
    if "cinepolis" in p or "cinépolis" in p:
        return "cinepolis"
    return None


def hub_path(key: str) -> str:
    return f"/{APPS[key][0]}-offers/"


def offer_row(o: Offer, today: date, with_app=False, link_card=True) -> list:
    name = f'<a href="/bank/{o.slug}/#{E(o.id)}">{E(who(o))}</a>' if (o.is_bank and link_card) else E(who(o))
    row = [name] + ([E(where(o))] if with_app else []) + [
        E(what(o)), E(cap(o)), E(day_rule(o, today)[1] if link_card else re.sub(r" · (?:next )?[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}$", "", day_rule(o, today)[1])),
        E(key_col(o, today) if link_card else re.sub(r" \(next: \d{1,2} [A-Z][a-z]{2}\)", "", key_col(o, today))),
        E(fmt_day(o.valid_to)) if o.valid_to else "Not stated", ext(o.source_url, E(domain(o.source_url)))]
    return row


def key_col(o: Offer, today: date) -> str:
    """Key condition for a table that already has a Days column: never the booking day twice."""
    g_ = gate(o, today)
    if g_ and g_.startswith("Book on"):
        return times(o.monthly_limit) if o.monthly_limit else "See the terms"
    return key_condition(o, today)


ROW_HEAD = ["Card or pass", "Benefit", "Cap", "Days", "Key condition", "Ends", "Terms"]


def spot_rows(spots: list) -> str:
    """Spotted leads as a compact list (same data attributes as a spotted card, so the 7-day rule still hides them)."""
    li = "".join(
        f'<li class="spot sp-row" id="{x.dom_id}" data-spotted="{x.spotted_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        f'data-valid-to="{x.valid_to.isoformat() if x.valid_to else ""}"><span class="sp-who">{E(x.issuer)}</span> '
        f'<span>{E(x.headline)}</span><span class="sp-foot">Spotted on {E(x.source_name)} · '
        f'{E(fmt_dm(x.spotted_at.astimezone(IST).date()))} · '
        + (ext(PVR_HOME, "pvrcinemas.com", sr="PVR INOX home page") if x.is_pvr else ext(x.source_url, "Source", sr=E(x.source_name)))
        + (f' · code {E(x.code)} (unverified)' if x.code else "") + "</span></li>" for x in spots)
    return f'<ul class="sp-list">{li}</ul>'


def related_links(site: "Site", skip: str = "") -> str:
    apps = "".join(f'<li><a href="{pth}">{E(n)} offers</a></li>' for pth, n in site.apps if pth != skip)
    banks = "".join(f'<li><a href="/bank/{s}/">{E(site.bank_name(n))} offers</a></li>' for s, n in site.banks if f"/bank/{s}/" != skip)
    more = (f'<li><a href="{site.week}">This week</a></li>' if site.week and site.week != skip else "") + \
        '<li><a href="/best-card-for-movie-tickets/">Best card for movie tickets</a></li>'
    return ('<section class="wrap block" aria-labelledby="h-rel"><div class="sec-head"><h2 id="h-rel">More offers</h2></div>'
            f'<ul class="links">{apps}{banks}{more}</ul></section>')


def page_app(site: "Site", key: str, offers: list, spots: list, changes: list, today: date, warn: list) -> Page:
    slug, app = APPS[key]
    path = hub_path(key)
    movie = sorted([o for o in offers if o.is_movie], key=lambda o: (-cap_num(o), o.id))
    events = [o for o in offers if not o.is_movie]
    stamp = stamp_of(offers)
    d, dm = fmt_day(stamp.astimezone(IST).date()), fmt_dm(stamp.astimezone(IST).date())
    n = len(movie)
    parts = []
    for o in movie:
        g_ = gate_short(o, today)
        parts.append(f"{who(o)}: {what(o)}, {cap(o)}" + (f" ({g_})" if g_ else ""))
    top = movie[0] if movie else None
    answer = (f"<strong>{n} movie offer{'s' if n != 1 else ''} on {E(app)} pass{'es' if n == 1 else ''} our checks on {d}.</strong> "
              f"{E('; '.join(parts))}." if movie else
              f"<strong>No movie offer on {E(app)} passes our checks on {d}.</strong>")
    if top and cap_num(top):
        answer += f" Highest cap: ₹{cap_num(top):,} ({E(who(top))})."
    body = ""
    if movie:
        body += (f'<section class="wrap block" aria-labelledby="h-cmp"><div class="sec-head"><h2 id="h-cmp">{E(app)} offers compared</h2>'
                 f'<p class="meta">Highest cap first</p></div>'
                 + table([offer_row(o, today) for o in movie], ROW_HEAD, f"{E(app)} movie offers, checked {fmt_stamp(stamp)}", movie)
                 + '</section>')
        body += (f'<section class="wrap block" aria-labelledby="h-each"><div class="sec-head"><h2 id="h-each">Each offer, with its terms</h2></div>'
                 f'<div class="grid">{"".join(offer_card(site, o, today, warn, path) for o in movie)}</div></section>')
    for o in events:
        body += (f'<section class="wrap block"><p class="stat"><strong>Also checked on {E(app)}: live events, not movies.</strong> '
                 f'{E(who(o))}: {E(what(o))}, {E(cap(o))}. {ext(o.source_url, "Terms on " + E(domain(o.source_url)))}</p></section>')
    if spots:
        body += (f'<section class="wrap block spotted" id="spotted" data-spot-section aria-labelledby="h-sp"><div class="sec-head">'
                 f'<h2 id="h-sp"><span aria-hidden="true">👀 </span>Spotted for {E(app)}: not yet verified</h2>'
                 f'<p class="meta">{len(spots)} spotted · newest first</p></div><p class="sp-intro">{E(SPOT_INTRO)}</p>'
                 f'{spot_rows(spots)}<p><a class="more" href="/spotted/">All spotted offers {icon("arrow")}</a></p></section>')
    hist = [c for c in changes if c["id"] in {o.id for o in offers}][:6]
    if hist:
        body += ('<section class="wrap block" aria-labelledby="h-h"><div class="sec-head"><h2 id="h-h">Recent changes</h2>'
                 f'<a class="more" href="/changes/">All changes {icon("arrow")}</a></div><ol class="log">'
                 + "".join(f'<li class="log-i"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span><p>{E(c["text"])}</p></li>'
                           for c in hist) + "</ol></section>")
    body += related_links(site, path)
    kinds = sorted({what(o) for o in movie})
    title = fit_title([f"{app} offers: {what(top)} {cap(top)} ({dm})" if top else f"{app} offers ({dm})",
                       f"{app} offers: {what(top)} {cap(top)}" if top else f"{app} offers", f"{app} offers"])
    desc = (f"FDFS (Film · Deals · Friends · Seats): {n} {app} movie offer{'s' if n != 1 else ''} checked against the "
            f"official terms on {d}. " + "; ".join(f"{who(o)}: {what(o)} {cap(o)}" for o in movie[:3]) + "."
            if movie else f"FDFS: no {app} movie offer passes our checks on {d}.")
    key_ = facts(offers) + json.dumps([x.id for x in spots]) + json.dumps(hist, sort_keys=True) + "".join(key_condition(o, today) for o in movie)
    banks = len({o.issuer for o in movie})
    og = og_hub(f"app-{slug}", f"{app} offers", movie,
                f"{og_count(movie)} · {banks} bank{'s' if banks != 1 else ''}" if movie and all(o.is_bank for o in movie) else "")
    items = [{"@type": "ListItem", "position": i + 1, "name": f"{who(o)}: {what(o)}, {cap(o)}",
              "url": f"{site.base}{path}#{o.id}"} for i, o in enumerate(movie)]
    return Page(path, title, desc, f"{E(app)} movie ticket offers, <em>checked.</em>", answer, body,
                [("Offers", "/"), (f"{app} offers", path)], "Checked", stamp, key_ + "|".join(kinds), og=og,
                extra_ld=[{"@type": "ItemList", "name": f"{app} movie ticket offers", "itemListElement": items}] if items else [],
                js=SPOT_JS if spots else "")


def page_bank_app(site: "Site", slug: str, key: str, offers: list, today: date, warn: list) -> Page:
    """Only built when a bank has checked offers on 2+ apps: then 'HDFC BookMyShow offer' gets its own answer."""
    app_slug, app = APPS[key]
    name, short = site.bank_name(offers[0].issuer), offers[0].issuer
    path = f"/bank/{slug}/{app_slug}/"
    movie = sorted([o for o in offers if o.is_movie], key=lambda o: (-cap_num(o), o.id))
    stamp = stamp_of(offers)
    d, dm = fmt_day(stamp.astimezone(IST).date()), fmt_dm(stamp.astimezone(IST).date())
    parts = [f"{who(o)}: {what(o)}, {cap(o)}" + (f" ({gate_short(o, today)})" if gate_short(o, today) else "") for o in movie]
    answer = (f"<strong>Yes. {len(movie)} {E(short)} offer{'s' if len(movie) != 1 else ''} on {E(app)} pass{'es' if len(movie) == 1 else ''} "
              f"our checks on {d}:</strong> {E('; '.join(parts))}.")
    body = (f'<section class="wrap block"><div class="sec-head"><h2>{E(short)} on {E(app)}, compared</h2></div>'
            + table([offer_row(o, today) for o in movie], ROW_HEAD, f"{E(name)} offers on {E(app)}, checked {fmt_stamp(stamp)}", movie)
            + f'</section><section class="wrap block"><div class="grid">{"".join(offer_card(site, o, today, warn, path, link_bank=False) for o in movie)}</div>'
            f'<p><a class="more" href="/bank/{slug}/">All {E(name)} offers {icon("arrow")}</a> · '
            f'<a class="more" href="{hub_path(key)}">All {E(app)} offers {icon("arrow")}</a></p></section>' + related_links(site, path))
    top = movie[0]
    title = fit_title([f"{short} {app} offer: {what(top)} {cap(top)} ({dm})", f"{short} {app} offer: {what(top)} {cap(top)}",
                       f"{short} {app} offer"])
    desc = f"FDFS: {len(movie)} {name} offer{'s' if len(movie) != 1 else ''} on {app}, checked {d}. " + "; ".join(parts[:3]) + "."
    return Page(path, title, desc, f"Does {E(short)} have a {E(app)} offer?", answer, body,
                [("Offers", "/"), (f"{name} offers", f"/bank/{slug}/"), (app, path)], "Checked", stamp,
                facts(offers) + "".join(key_condition(o, today) for o in movie))


def week_of(d: date) -> tuple:
    y, w, _ = d.isocalendar()
    mon = d - timedelta(days=d.weekday())
    return y, w, mon


def week_label(mon: date) -> str:
    sun = mon + timedelta(days=6)
    if mon.year != sun.year:
        return f"{fmt_day(mon)} – {fmt_day(sun)}"
    if mon.month != sun.month:
        return f"{fmt_dm(mon)} – {fmt_dm(sun)} {sun.year}"
    return f"{mon.day}–{sun.day} {sun:%b %Y}"


def week_path(y: int, w: int, current: bool) -> str:
    return "/this-week/" if current else f"/this-week/{y}-w{w:02d}/"


def weekly_pages(site: "Site", offers: list, changes: list, hist: Path, now: datetime, spots: list) -> list:
    """One dated digest per ISO week with data. The running week is /this-week/; a finished week keeps a permanent
    /this-week/YYYY-wNN/ built from that week's last snapshot. Article dates are real: datePublished is the week's
    first export, dateModified the page's own 'Updated' stamp."""
    today = now.astimezone(IST).date()
    cy, cw, cmon = week_of(today)
    snaps = {}
    for f in sorted(Path(hist).glob("*.json")) if hist and Path(hist).exists() else []:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f.name):
            continue
        y, w, mon = week_of(date.fromisoformat(f.stem))
        snaps.setdefault((y, w, mon), []).append(f)
    weeks = dict(snaps)
    weeks.setdefault((cy, cw, cmon), [])
    built, pages = [], []
    for (y, w, mon), files in sorted(weeks.items()):
        current = (y, w) == (cy, cw)
        if current:
            shown_ = [o for o in offers if o.is_movie]
            first = min([_dt(json.loads(f.read_text()).get("generated_at")) or now for f in files] + [now])
            asof = now
        else:
            last = json.loads(files[-1].read_text(encoding="utf-8"))
            asof = _dt(last.get("generated_at"))
            if asof is None:
                continue
            shown_ = [o for o in (norm(r) for r in last.get("offers") or []) if o.is_movie and publishable(o, asof, site.cfg)[0]]
            first = min(_dt(json.loads(f.read_text()).get("generated_at")) or asof for f in files)
        if not shown_:
            continue                                                    # no thin pages: a week with nothing to list
        built.append((y, w, mon, current, shown_, first, asof))
    for i, (y, w, mon, current, shown_, first, asof) in enumerate(built):
        path = week_path(y, w, current)
        label = week_label(mon)
        sun = mon + timedelta(days=6)
        wk = [c for c in changes if mon.isoformat() <= c["date"] <= sun.isoformat()]
        added = sum(1 for c in wk if c["type"] in ("first_check", "added"))
        chg = sum(1 for c in wk if c["type"] == "changed")
        ended = sum(1 for c in wk if c["type"] == "removed")
        movie = sorted(shown_, key=lambda o: (-cap_num(o), o.id))
        caps = sorted({cap_num(o) for o in movie if cap_num(o)})
        rng = (f"₹{caps[0]:,}–₹{caps[-1]:,}" if len(caps) > 1 else f"₹{caps[0]:,}") if caps else ""
        tail = (f" {added} first checked or new, {chg} changed, {ended} ended or withdrawn." if wk
                else " No new, changed or ended offers were recorded this week.")
        answer = (f"<strong>Week of {E(label)}: {len(movie)} movie offer{'s' if len(movie) != 1 else ''} "
                  f"{'pass' if current else 'passed'} our checks</strong>" + (f", with caps of {rng}." if rng else ".") + E(tail))
        changes_html = ('<ol class="log log-1">' + "".join(
            f'<li class="log-i"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span><p>{E(c["text"])}</p></li>'
            for c in wk) + "</ol>") if wk else '<p class="log-one">Nothing new, changed or ended this week.</p>'
        rows = [offer_row(o, today if current else asof.astimezone(IST).date(), with_app=True, link_card=current) for o in movie]
        head = ["Card or pass", "Where"] + ROW_HEAD[1:]
        tbl = table(rows, head, f"Movie offers {'that pass' if current else 'that passed'} our checks, week of {E(label)}",
                    movie if current else None)
        nav = []
        if i > 0:
            py, pw, pmon, pcur = built[i - 1][:4]
            nav.append(f'<a href="{week_path(py, pw, pcur)}">← Week of {E(week_label(pmon))}</a>')
        if i < len(built) - 1:
            ny, nw, nmon, ncur = built[i + 1][:4]
            nav.append(f'<a href="{week_path(ny, nw, ncur)}">Week of {E(week_label(nmon))} →</a>')
        spot_line = (f'<p class="log-one">Also this week: {len(spots)} offer{"s" if len(spots) != 1 else ""} spotted on the web, '
                     f'not yet verified. <a href="/spotted/">See them, with sources</a>.</p>') if current and spots else ""
        body = (f'<section class="wrap block"><p class="meta">Week of {E(label)} · first published '
                f'<time datetime="{iso(first)}">{E(fmt_stamp(first))}</time></p></section>'
                f'<section class="wrap block" aria-labelledby="h-wc"><div class="sec-head"><h2 id="h-wc">What changed</h2>'
                f'<a class="more" href="/changes/">All changes {icon("arrow")}</a></div>{changes_html}</section>'
                f'<section class="wrap block" aria-labelledby="h-wo"><div class="sec-head"><h2 id="h-wo">The offers, compared</h2>'
                f'<p class="meta">Highest cap first</p></div>{tbl}{spot_line}</section>'
                + (f'<nav class="wrap block week-nav" aria-label="Other weeks">{" ".join(nav)}</nav>' if nav else "")
                + (related_links(site, path) if current else ""))
        h1 = f"Movie ticket offers this week: {E(label)}" if current else f"Movie ticket offers, week of {E(label)}"
        title = fit_title([f"Movie ticket offers this week ({label})" if current else f"Movie ticket offers, week of {label}",
                           f"Movie ticket offers, week of {label}"])
        desc = (f"FDFS (Film · Deals · Friends · Seats): the movie ticket offers that {'pass' if current else 'passed'} our checks "
                f"in the week of {label}, compared, with what changed.{tail}")
        art = {"@type": "Article", "headline": re.sub("<[^>]+>", "", h1), "datePublished": iso(first),
               "dateModified": iso(asof), "author": {"@id": site.base + "/#org"}, "publisher": {"@id": site.base + "/#org"},
               "mainEntityOfPage": {"@id": site.base + path}, "inLanguage": "en-IN"}
        crumbs = [("Offers", "/"), ("This week", "/this-week/")] if current else \
            [("Offers", "/"), ("This week", "/this-week/"), (f"Week of {label}", path)]
        pg = Page(path, title, desc, h1, answer, body, crumbs, "Updated", asof,
                  facts(movie) + json.dumps(wk, sort_keys=True) + label, extra_ld=[art], og=None)
        pg.published = first
        pages.append(pg)
    return pages


def prose_page(path, title, desc, h1, answer, prose, crumb, stamp, extra_ld=None) -> Page:
    body = f'<section class="wrap block"><div class="prose">{prose}</div></section>'
    return Page(path, title, desc, h1, answer, body, [("Offers", "/"), (crumb, path)], "Updated", stamp, prose + answer,
                extra_ld=extra_ld or [])


MCP_PATH = "/mcp/fdfs_mcp.py"    # decision 170: served from this site; the source is gen/fdfs_mcp.py
MCP_URL = "https://fdfs-mcp.deepakthegiggs.workers.dev/mcp"  # hosted copy (gen/mcp-worker), live 27 Nov 2026


def agents_page(site: Site, offers: list, now: datetime) -> Page:
    """Decision 170 (owner: "make FDFS work with agents"): how an AI agent can query the checked offers. The MCP server
    is a small read-only script; the same tools are also hosted at MCP_URL (Cloudflare Worker built from it). Both read
    /offers.json only."""
    base = site.base
    cfg_json = '{"mcpServers": {"fdfs": {"command": "python3", "args": ["/path/to/fdfs_mcp.py"]}}}'
    prose = f'''<h2>MCP server</h2>
<p>FDFS has a small {ext("https://modelcontextprotocol.io/", "Model Context Protocol")} server, so an assistant or agent can answer "which of my cards gets me a deal on this booking?" from our checked offers. Each answer has the cap, the key condition, the end date, the official source, when we checked it, a message ready to send your group, and a link to the offer's page here.</p>
<h3>Connect by address (nothing to install)</h3>
<p>Add this address as a custom connector in your assistant (it speaks Streamable HTTP, no sign-in):</p>
<pre><code>{E(MCP_URL)}</code></pre>
<p>In Claude Code: <code>claude mcp add --transport http fdfs {E(MCP_URL)}</code></p>
<h3>Or run it yourself</h3>
<ol><li>Download <a href="{MCP_PATH}" download>fdfs_mcp.py</a>. It's one file, standard-library Python 3.9 or later, read-only.</li>
<li>Add it to your MCP client (Claude Desktop, Claude Code, Cursor and others take the same shape):<pre><code>{E(cfg_json)}</code></pre></li></ol>
<p>Then ask about movie ticket offers, for example "I have Axis My Zone and HDFC Diners Club Privilege. Which one for 2 tickets on District this Saturday?"</p>
<h2>Tools</h2>
<ul><li><code>match_cards</code>: the cards in your wallet, plus the app, day and number of tickets if you know them. For each card, the offers it qualifies for, best first, and whether the terms name that card or only its bank.</li>
<li><code>find_offers</code>: every checked offer, by day, app, bank or free text.</li>
<li><code>get_offer</code>: one offer's full recorded terms, with the quotes from the official page.</li>
<li><code>list_banks</code>: which banks have checked offers now, and on which apps.</li></ul>
<p>Both read <a href="/offers.json">/offers.json</a> and nothing else. The downloaded script keeps the cards you name on your computer. The hosted server gets only what your assistant sends it, uses it to answer, and keeps no record. It never returns spotted leads, leaves out offers past their end date, and flags any offer we haven't re-checked in 7 days.</p>
<h2>Data feeds</h2>
<ul><li><a href="/offers.json">offers.json</a>: every checked offer with its source, quotes and check time (CC BY 4.0).</li>
<li><a href="/llms-full.txt">llms-full.txt</a>: the same offers as plain text.</li>
<li><a href="/llms.txt">llms.txt</a>: our key pages, for answer engines.</li>
<li><a href="/changes.json">changes.json</a> and <a href="/changes.xml">changes.xml</a>: what changed, dated.</li></ul>
<h2>Using our data</h2>
<p>Credit "FDFS (bookmyfdfs.in)" and link the offer's page (each offer's <code>url</code>). Say when we checked it, and tell people to read the terms before they pay: quotas and spend rules can't be checked from outside.</p>'''
    n = len(offers)
    return prose_page("/agents/", "Use FDFS from an assistant or agent: MCP server · FDFS",
                      "Let an assistant or agent answer movie ticket offer questions from FDFS's checked offers: a read-only MCP server, plus open JSON and text feeds.",
                      "Use FDFS from an assistant or agent",
                      f"<strong>Your assistant or agent can query our {n} checked offer{'s' if n != 1 else ''}.</strong> Connect the read-only FDFS MCP server by its address, or read the open feeds.",
                      prose, "For agents", now)


def trust_pages(site: Site, offers: list[Offer], now: datetime, spotted: bool = False) -> list[Page]:
    email = site.cfg.get("contact_email")
    contact_section = (f'<h2>Contact</h2><p>Email <a href="mailto:{E(email)}">{E(email)}</a>.</p>' if email else "")
    sources = ["banks"] + (["UPI apps"] if any(o.category in ("upi", "wallet") for o in offers) else []) + \
        (["memberships"] if any(o.category == "membership" for o in offers) else [])
    spot_how = ("<h2>Spotted, not yet verified</h2><p>Some offers we've only seen on the web: in the news, in a bank's posts or "
                "on an aggregator listing. We show them in a separate <a href=\"/spotted/\">Spotted</a> section with the source, "
                "the date we saw them and a short quote, and never as checked. A spotted offer disappears 7 days after we last "
                "saw it, or as soon as we verify it. We find them through search results and sources that allow reading; sites "
                "that block automated reads are checked by hand only.</p>") if spotted else ""
    how = f'''<h2>What it reads</h2>
<ul><li>Banks' own offer and terms pages and PDFs (for example hsbc.bank.in, axis.bank.in, indusind.bank.in).</li>
<li>Some terms sit on sites whose own terms ban automated reads, such as a ticketing app's policy pages. FDFS Offer Intelligence doesn't read those. An offer from such a page is published only after our team has read the terms, and it's labelled "terms read by our team".</li></ul>
<h2>What we never read</h2>
<ul><li>We never read ticketing apps automatically: not their offer, checkout or seat pages, and no private endpoints. Their terms forbid it.</li>
<li>Coupon and aggregator sites. A claim seen only there is never published as checked.</li></ul>{spot_how}
<h2>How a check works</h2>
<ol><li><strong>Read.</strong> FDFS Offer Intelligence fetches the official page politely: robots.txt respected, at most one request every 10 seconds per site, an honest user agent, never past a block.</li>
<li><strong>Extract with a quote.</strong> Every fact (the cap, the days, the limit, the end date, the code) must come with the exact sentence from the page that states it. No quote, no fact.</li>
<li><strong>Verify in code.</strong> Code checks that each quote is really on the page and really says that fact: the amount, the day, the limit. A fact that fails is dropped.</li>
<li><strong>Re-read to confirm.</strong> A second, fresh read must still contain every quote. If two pages disagree, or the page contradicts itself, the offer is held back.</li>
<li><strong>Date it.</strong> Each offer shows when it was last checked, in IST. An offer not re-checked for 7 days is no longer shown as valid.</li>
<li><strong>Expire it.</strong> On its end date, an offer stops being shown as valid and moves to the <a href="/changes/">changes log</a>.</li></ol>
<h2>What "checked" does and doesn't mean</h2>
<p>"Checked" means the official terms said this on that date and time. It doesn't mean the bank or the app verified anything for us, that the offer will work for your card, or that its quota hasn't run out that day. Spend gates and first-come quotas can't be checked from outside.</p>
<h2>Open data</h2>
<p>The same data is published at <a href="/offers.json">/offers.json</a> and <a href="/changes.json">/changes.json</a> under CC BY 4.0.</p>'''
    base = site.base
    dataset = {"@type": "Dataset", "@id": base + "/offers.json#dataset", "name": "FDFS checked movie ticket offers (India)",
               "description": "Movie ticket offers from banks and memberships in India, each with its official source URL, verbatim quotes and the date and time it was checked.",
               "url": base + "/how-we-check/", "license": "https://creativecommons.org/licenses/by/4.0/",
               "creator": {"@id": base + "/#org"}, "isAccessibleForFree": True, "dateModified": iso(now),
               "distribution": [{"@type": "DataDownload", "contentUrl": base + "/offers.json", "encodingFormat": "application/json"},
                                {"@type": "DataDownload", "contentUrl": base + "/changes.json", "encodingFormat": "application/json"}]}
    about = f'''<p><strong>FDFS stands for Film · Deals · Friends · Seats</strong>: the four things every movie plan comes down to.</p>
<p>FDFS is an independent site. It starts with the money side of a movie plan: ticket offers from {join_and(sources)}, each one read from its official terms and dated. Next come pages on what's new in your city and when booking opens.</p>
<h2>Independence</h2><p>{FOOTER_LINE} We don't sell tickets, cards or memberships, and we don't take payment to list or rank an offer.</p>
{contact_section}<h2>Corrections</h2><p>Every fix to a published fact is logged publicly on the <a href="/corrections/">Corrections</a> page.</p>'''
    spot_fix = ("<h2>Spotted offers</h2><p>Spotted offers are leads we haven't checked. Tell us if a spotted offer is wrong"
                + (f' at <a href="mailto:{E(email)}">{E(email)}</a>' if email else "")
                + ": we re-read the source, remove or correct the entry, and log it here.</p>") if spotted else ""
    corrections = f"""<h2>How we handle errors</h2><p>When a published fact turns out to be wrong or out of date, we re-read the official terms, fix the page, and log the correction below with its date and what changed. Corrections are public and are never deleted.</p>
{spot_fix}<h2>Log</h2><p>No corrections yet.</p>"""
    disclosures = '''<ul><li><strong>No affiliate links.</strong> If that ever changes, each such link will be labelled right next to it.</li>
<li><strong>No paid placements.</strong> No bank, app or cinema pays to be listed or ranked.</li>
<li><strong>No cookies.</strong> The site sets no cookies. We count visits with Cloudflare Web Analytics, which is cookieless and aggregate. It never sees the cards you pick, which stay on your device.</li>
<li><strong>Names, not logos.</strong> Bank, app and cinema names are used only to say where an offer applies. We are not affiliated with any of them.</li>
<li><strong>Sharing.</strong> "Share on WhatsApp" opens WhatsApp with the offer's text. We don't track it.</li>
<li><strong>Open data.</strong> The offer data is published at <a href="/offers.json">/offers.json</a> and <a href="/changes.json">/changes.json</a> under CC BY 4.0. Please credit "FDFS (bookmyfdfs.in)" and link the page. Quoted terms remain their owners'; the licence covers FDFS's compilation and structure.</li></ul>'''
    return [agents_page(site, offers, now),
        prose_page("/how-we-check/", "How FDFS Offer Intelligence checks offers · FDFS",
                   "FDFS Offer Intelligence reads each official terms page and confirms every detail against its exact words. What it reads, what we never read, and what 'checked' means.",
                   "How FDFS Offer Intelligence checks offers",
                   "<strong>FDFS Offer Intelligence reads each official terms page and confirms every detail against its exact words.</strong> Code verifies every quote; anything it can't confirm isn't shown.",
                   how, "How we check", now, [dataset]),
        prose_page("/about/", "About: Film · Deals · Friends · Seats · FDFS",
                   "FDFS (Film · Deals · Friends · Seats) is an independent site that checks movie ticket offers against their official terms.",
                   "What is FDFS?", "<strong>FDFS stands for Film · Deals · Friends · Seats.</strong> It's an independent site that checks movie ticket offers against their official terms.",
                   about, "About", now),
        prose_page("/corrections/", "Corrections log · FDFS", "The public log of every fix to a published offer fact.",
                   "Corrections", "<strong>No corrections so far.</strong> Every fix to a published fact is logged here with its date.",
                   corrections, "Corrections", now),
        prose_page("/disclosures/", "Disclosures: no affiliate links, no cookies · FDFS",
                   "FDFS has no affiliate links, no paid placements and no cookies. Offer data is open under CC BY 4.0.",
                   "Disclosures", "<strong>No affiliate links, no paid placements, no cookies.</strong> The offer data is open under CC BY 4.0.",
                   disclosures, "Disclosures", now),
    ]


# ---------------------------------------------------------------- changes (from dated snapshots)
TRACKED = ("value", "cap_text", "days", "day_basis", "show_days", "monthly_limit", "min_tickets", "valid_to",
           "code", "platform", "channel", "quota_note", "requires_purchase", "card_variants", "variants_scope")


def changes_from_history(hist_dir: Path, cfg: dict | None = None) -> list[dict]:
    snaps = sorted(p for p in Path(hist_dir).glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name))
    out, prev = [], None
    for p in snaps:
        day = p.stem
        snap = json.loads(p.read_text(encoding="utf-8"))
        at = _dt(snap.get("generated_at"))
        # the same guard as the live pages: a record that wasn't showable then never enters the log
        cur = {r["id"]: r for r in snap.get("offers", []) if r.get("id") and at and publishable(norm(r), at, cfg or {})[0]}

        def rec(i, o, typ, label, text, when):
            return {"date": day, "at": iso(when), "id": i, "issuer": o.issuer, "type": typ, "label": label,
                    "who": who(o), "text": text}
        if prev is None:
            for i in sorted(cur):
                o = norm(cur[i])
                out.append(rec(i, o, "first_check", "First checked", f"{who(o)} on {where(o)}: {what(o)}, {cap(o)}.",
                               o.checked_at or at))
        else:
            for i in sorted(set(cur) - set(prev)):
                o = norm(cur[i])
                out.append(rec(i, o, "added", "New", f"{who(o)} on {where(o)}: {what(o)}, {cap(o)}.", o.checked_at or at))
            for i in sorted(set(prev) - set(cur)):
                o = norm(prev[i])
                vt = o.valid_to
                if vt and vt.isoformat() < day:
                    out.append(rec(i, o, "removed", "Ended", f"{who(o)} on {where(o)} ended on {fmt_day(vt)}.", at))
                else:
                    out.append(rec(i, o, "removed", "No longer shown",
                                   f"{who(o)} on {where(o)}: its terms could not be re-confirmed.", at))
            for i in sorted(set(cur) & set(prev)):
                diffs = [k for k in TRACKED if prev[i].get(k) != cur[i].get(k)]
                if diffs:
                    o = norm(cur[i])
                    out.append(rec(i, o, "changed", "Changed",
                                   f"{who(o)} on {where(o)}: {', '.join(k.replace('_', ' ') for k in diffs)} changed. Now: {what(o)}, {cap(o)}.",
                                   o.checked_at or at))
        prev = cur
    out.sort(key=lambda c: (c["date"], c["id"]), reverse=True)
    return out


# ---------------------------------------------------------------- per-offer pages (L1, decision 141)
# One stable page per offer at /offer/<id>/. Live offers: the receipt (every term, unknowns said as unknowns), the exact
# quotes, the dated check and the change history, plus Offer JSON-LD built from the same strings. An offer that had a page
# and is no longer shown keeps it: marked as history, noindex, no Offer JSON-LD, out of the sitemap (009 A6).
FRESHNESS_POLICY = {"fresh_hours": 48, "short_campaign_fresh_hours": 24, "short_campaign_days": 14, "hide_after_days": 7}


def freshness(o: Offer, now: datetime, policy: dict | None = None) -> str:
    """009 A1: 'fresh' | 'needs_recheck' | 'unconfirmed', recomputed from the original checked_at at build time.
    A published per-row value can only make it stricter, never fresher. A row without one is computed, never dropped."""
    p = {**FRESHNESS_POLICY, **(policy or {})}
    if o.checked_at is None:
        return "unconfirmed"
    age = now - o.checked_at
    short = (o.valid_from and o.valid_to and (o.valid_to - o.valid_from).days + 1 < p["short_campaign_days"])
    fresh_h = p["short_campaign_fresh_hours"] if short else p["fresh_hours"]
    got = "fresh" if age <= timedelta(hours=fresh_h) else "needs_recheck" if age <= timedelta(days=p["hide_after_days"]) else "unconfirmed"
    order = ("fresh", "needs_recheck", "unconfirmed")
    pub = o.raw.get("freshness")
    return order[max(order.index(got), order.index(pub) if pub in order else 0)]


def offer_slug(oid: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(oid).lower()).strip("-") or "offer"


def offer_path(oid: str) -> str:
    return f"/offer/{offer_slug(oid)}/"


def offer_history(oid: str, changes: list) -> list[dict]:
    """THE history reader for an offer page, newest first: [{date, at, type, label, text}].
    Today it is derived from the dated snapshots in data/history (changes_from_history). When Codex's C1/C4 land
    (data/versions/<id>.jsonl, dist/offers/<id>.json, entry 007/009), switch this one function to read them; the page
    code only depends on this shape. Not reading those files yet: their exporter hasn't shipped."""
    return [c for c in changes if c.get("id") == oid]


def last_published(hist_dir: Path, cfg: dict) -> dict:
    """{id: (raw record, snapshot date)} for every offer that passed the site's guard in some snapshot: each one had
    a page (every shown offer gets one), so each keeps one."""
    seen = {}
    for p in sorted(Path(hist_dir).glob("*.json")) if hist_dir and Path(hist_dir).exists() else []:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name):
            continue
        snap = json.loads(p.read_text(encoding="utf-8"))
        at = _dt(snap.get("generated_at"))
        for r in snap.get("offers") or []:
            if r.get("id") and at and publishable(norm(r), at, cfg)[0]:
                seen[r["id"]] = (r, p.stem)
    return seen


FIELD_LABEL = {"value": "Benefit", "kind": "Benefit", "cap_text": "Cap", "card_variants": "Cards", "variants_scope": "Cards",
               "issuer": "Issuer", "display_name": "Card", "instrument": "Card type", "category": "Type", "platform": "App",
               "channel": "App or website", "days": "Days", "day_basis": "Booking or show day", "show_days": "Show days",
               "monthly_limit": "Limit", "min_tickets": "Minimum tickets", "quota_note": "Quota or spend rule", "code": "Code",
               "how_to_redeem": "How to redeem", "valid_from": "Start", "valid_to": "End", "excludes": "Exclusions",
               "requires_purchase": "Paid pass", "cities": "Cities", "max_benefit_per_booking": "Per booking"}


def field_label(k: str) -> str:
    if k.startswith("conditions:"):
        return CONDITIONS.get(k.split(":", 1)[1], "A condition")
    return FIELD_LABEL.get(k, k.replace("_", " ").capitalize())


def cards_text(o: Offer) -> str:
    """Eligible cards, never wider than the terms."""
    if o.category == "membership":
        return who(o)
    kind = "credit cards" if o.instrument == "credit" else "debit cards" if o.instrument == "debit" else "cards"
    if o.variants_scope == "unstated":
        return f"Select {o.issuer} {kind} (the terms don't list which)"
    if o.variants and o.variants_scope == "listed":
        return who(o) + " only"
    if o.variants_scope == "all":
        return f"All {o.issuer} {kind}, per the terms"
    return f"{o.issuer} {kind}"


def days_plain(o: Offer) -> str:
    if "any" in o.days:
        return "Every day"
    keys = sorted(day_keys(o), key=DAY_IDX.get)
    if not keys:
        return "Not stated in the terms"
    return " and ".join(f"{DAY[k]}s" for k in keys) + " only"


def basis_text(o: Offer) -> str:
    """Booking day vs show day, said plainly; an unstated basis is said to be unstated."""
    if o.day_basis == "booking":
        return "The day you book counts" + (". The show can be any day" if "any" in o.show_days else "")
    if o.day_basis == "show":
        return "The day of the show counts"
    if "any" in o.days:
        return "Any day, so it doesn't matter"
    return "Not stated in the terms"


def validity_text(o: Offer) -> str:
    if o.valid_from and o.valid_to:
        return f"{fmt_day(o.valid_from)} to {fmt_day(o.valid_to)}"
    if o.valid_to:
        return f"Until {fmt_day(o.valid_to)}"
    if o.valid_from:
        return f"From {fmt_day(o.valid_from)}. No end date stated in the terms"
    return "No end date stated in the terms"


def limit_text(o: Offer) -> str:
    bits = []
    if o.monthly_limit:
        bits.append(times(o.monthly_limit))
    if o.quota_note:
        bits.append(o.quota_note.rstrip("."))
    return ". ".join(bits) if bits else "Not stated in the terms"


def min_text(o: Offer) -> str:
    if o.min_tickets:
        return f"{o.min_tickets} tickets in one booking"
    if o.raw.get("min_tickets_basis") == "benefit_kind" or o.kind == "bogo":
        return "Not stated in the terms (a 2nd-ticket offer needs 2)"
    return "Not stated in the terms"


def receipt(site: "Site", o: Offer, today: date, warn: list) -> str:
    rows = [("Benefit", what(o)), ("Cap", cap(o)), ("Cards", cards_text(o)), ("Where", where(o)), ("Days", days_plain(o)),
            ("Booking or show day", basis_text(o)), ("Valid", validity_text(o)), ("Limit or quota", limit_text(o)),
            ("Minimum tickets", min_text(o))]
    if o.raw.get("max_benefit_per_booking"):
        rows.append(("Per booking", str(o.raw["max_benefit_per_booking"])))
    tl = tickets_line(o)
    if tl:
        rows.append(("Tickets", tl))
    g = spend_gate(o.quota_note)
    if g:
        rows.append(("Spend rule", g))
    rows.append(("Code", o.code if o.code else "None stated in the terms"))
    other = [CONDITIONS[c] for c in o.conditions if c in CONDITIONS] + [f"Not valid: {x}" for x in o.excludes]
    if any(c.startswith("bins:") for c in o.conditions):
        other.append("Only cards whose first digits (BIN) are listed in the terms")
    if other:
        rows.append(("Other conditions", ". ".join(other)))
    dl = "".join(f'<div class="rc-r"><dt>{E(k)}</dt><dd>{E(v)}</dd></div>' for k, v in rows)
    terms = " · ".join(ext(u, E(domain(u)) + icon("out"), sr="official terms") for u in o.terms_urls or [o.source_url])
    return (f'<div class="receipt"><p class="rc-h"><span>FDFS · offer receipt</span><span>{E(offer_slug(o.id))}</span></p>'
            f'<dl class="rc">{dl}</dl>'
            f'<p class="rc-f">Checked by {E(checked_by(o, site.cfg))} · <time datetime="{iso(o.checked_at)}">{E(fmt_stamp(o.checked_at))}</time></p>'
            f'<p class="rc-f">Terms: {terms}</p></div>')


def quotes_html(o: Offer) -> str:
    """Each distinct quote once, with the facts it supports and where it is from."""
    groups: dict = {}
    for k, qv in o.quotes.items():
        src = (o.raw.get("quote_sources") or {}).get(k) or o.source_url
        for q in (qv if isinstance(qv, list) else [qv]):      # a field may be backed by several spans
            if not q or not isinstance(q, str):
                continue
            gk = (q.strip(), src)
            groups.setdefault(gk, [])
            lab = field_label(k)
            if lab not in groups[gk]:
                groups[gk].append(lab)
    if not groups:
        return '<p class="log-one">The record has no stored quote. Read the terms page.</p>'
    return '<ul class="qs">' + "".join(
        f'<li><blockquote class="o-quote"><p>“{E(q)}”</p><cite>Supports: {E(", ".join(labs))} · '
        f'{ext(src, E(domain(src)))}</cite></blockquote></li>' for (q, src), labs in groups.items()) + "</ul>"


def history_html(hist: list) -> str:
    if not hist:
        return '<p class="log-one">No change recorded yet.</p>'
    return '<ol class="log log-1">' + "".join(
        f'<li class="log-i"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span><p>{E(c["text"])}</p>'
        f'<a href="/changes/#c-{E(c["date"])}-{E(c["id"])}">In the change log</a></li>' for c in hist) + "</ol>"


OFFER_CSS = '.receipt{max-width:640px;padding:18px 20px 30px;background:var(--surface);color:var(--text);box-shadow:var(--shadow-1);border-top:4px solid var(--accent-line);-webkit-mask:conic-gradient(from -45deg at bottom,#0000,#000 1deg 89deg,#0000 90deg) 50%/16px 100%;mask:conic-gradient(from -45deg at bottom,#0000,#000 1deg 89deg,#0000 90deg) 50%/16px 100%}.rc-h{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding-bottom:10px;border-bottom:2px dashed var(--line);font:700 var(--t-xs)/1.3 var(--font-code);letter-spacing:.06em;text-transform:uppercase;color:var(--text-2)}.rc{margin:0}.rc-r{display:grid;grid-template-columns:minmax(7rem,34%) 1fr;gap:4px 14px;padding:10px 0;border-bottom:1px dashed var(--line)}.rc dt{font-size:var(--t-xs);font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-3);padding-top:2px}.rc dd{margin:0;font-size:var(--t-sm);overflow-wrap:anywhere}.rc-r:first-child dd{font:700 1.25rem/1.2 var(--font-display)}.rc-r:nth-child(2) dd{font-weight:700;color:var(--accent-text)}@media (max-width:479px){.rc-r{grid-template-columns:1fr}}.rc-f{margin-top:10px;font-size:var(--t-xs);color:var(--text-2)}.rc-f a{display:inline-flex;align-items:center;gap:3px;font-weight:600}.qs{list-style:none;padding:0;display:grid;gap:10px;max-width:var(--measure)}.qs .o-quote{margin:0}.o-rc{display:block;margin-top:6px;font-weight:700}'


def offer_ld(site: "Site", o: Offer, name: str, desc: str) -> dict:
    """Offer markup: every value is a string the page shows (tests compare them)."""
    x = {"@type": "Offer", "@id": site.base + offer_path(o.id) + "#offer", "name": name, "description": desc,
         "url": site.base + offer_path(o.id), "category": "Movie ticket offer" if o.is_movie else "Live event ticket offer",
         "offeredBy": {"@type": "Organization", "name": o.issuer}, "eligibleRegion": {"@type": "Country", "name": "India"}}
    if o.valid_from:
        x["validFrom"] = o.valid_from.isoformat()
    if o.valid_to:
        x["validThrough"] = o.valid_to.isoformat()
    return x


def page_offer(site: "Site", o: Offer, changes: list, today: date, warn: list, status: str = "current",
               ended_on: str | None = None) -> Page:
    """status: current | needs_recheck (live, indexed) or expired | withdrawn (history: noindex, no Offer markup)."""
    live = status in ("current", "needs_recheck")
    path = offer_path(o.id)
    name = f"{who(o)} on {app_name(o)}: {what_full(o)}"
    desc_short = f"{what(o)}, {cap(o)}"
    hist = offer_history(o.id, changes)
    if live:
        kc = key_condition(o, today)
        answer = (f"<strong>{E(name)}, {E(cap(o))}.</strong> {E(kc.rstrip('.'))}. {E(validity_text(o))}."
                  + (f" <span class=\"o-rc\">{E(recheck_line(o, site.now))}</span>" if status == "needs_recheck" else ""))
        h1 = f"{E(who(o))} on {E(app_name(o))}: <em>{E(what_full(o))}</em>"
        stamp_kind = "Checked"
    else:
        why = (f"It ended on {fmt_day(o.valid_to)}." if status == "expired" and o.valid_to else
               "Its terms could not be re-confirmed, so we stopped showing it.")
        answer = (f"<strong>No longer shown. {E(why)}</strong> Kept here as a record of what the terms said when we last "
                  f"checked{f' ({E(fmt_day(_d(ended_on)))})' if ended_on else ''}. Don't rely on it: see the "
                  f"<a href=\"/\">offers that pass our checks</a>.")
        h1 = f"{E(who(o))} on {E(app_name(o))}: {E(what_full(o))} <em>(no longer shown)</em>"
        stamp_kind = "Last checked"
        # decision 148: a visible status badge on the stable URL, then current alternatives from the same bank or app
        if status == "expired" and o.valid_to:
            badge = f"Expired on {fmt_dm(o.valid_to) if o.valid_to.year == today.year else fmt_day(o.valid_to)}"
        else:
            badge = "Withdrawn" + (f" · last seen {fmt_dm(_d(ended_on))}" if ended_on and _d(ended_on) else "")
    crumbs = [("Offers", "/")]
    if live and o.is_bank and any(s == o.slug for s, _ in site.banks):
        crumbs.append((f"{site.bank_name(o.issuer)} offers", f"/bank/{o.slug}/"))
    elif not live:
        crumbs.append(("Changes", "/changes/"))
    crumbs.append((name, path))
    more = []
    if live and o.is_bank and any(s == o.slug for s, _ in site.banks):
        more.append(f'<li><a href="/bank/{o.slug}/">All {E(site.bank_name(o.issuer))} offers</a></li>')
    k = app_key(o.platform)
    if live and k and any(p == hub_path(k) for p, _ in site.apps):
        more.append(f'<li><a href="{hub_path(k)}">All {E(APPS[k][1])} offers</a></li>')
    if live:
        more += [f'<li><a href="{card_path_of(o, v)}">{E(site_card_name(site, card_path_of(o, v)))}: every app</a></li>'
                 for v in o.variants if o.variants_scope == "listed" and site_card_name(site, card_path_of(o, v))]
        more += [f'<li><a href="{pth}">{E(lab)}</a></li>' for pth, lab in site.days
                 if any(DAY[k].lower() in pth for k in day_keys(o)) or "any" in o.days]
    if site.guide:
        more.append(f'<li><a href="{site.guide}">How card offers work</a></li>')
    more.append('<li><a href="/">Every offer that passes our checks</a></li>')
    alt = alternatives_section(site, o) if not live else ""
    ou = site.base + path
    plan_row = share_row(f"{who(o)} on {where(o).split(' · ')[0]}: {what(o)}, {cap(o)}. {key_condition(o, today)}."
                         f"{until_text(o, today)} Checked {fmt_day(o.checked_at.astimezone(IST).date())} from {domain(o.source_url)}.", ou,
                         ics_button(o, ou)) if live else ""
    body = plan_row + alt + (f'<section class="wrap block" aria-labelledby="h-rc"><div class="sec-head"><h2 id="h-rc">'
            f'{"The offer, line by line" if live else "What the terms said when last checked"}</h2>{PLAN.save_button(o, not live)}</div>'
            f'{receipt(site, o, today, warn)}{PLAN.checklist(site.plan_offers, o) if live else ""}</section>'
            f'<section class="wrap block" aria-labelledby="h-q"><div class="sec-head"><h2 id="h-q">The exact words in the terms</h2></div>'
            f'{quotes_html(o)}</section>'
            f'<section class="wrap block" aria-labelledby="h-hi"><div class="sec-head"><h2 id="h-hi">Change history</h2>'
            f'<a class="more" href="/changes/">All changes {icon("arrow")}</a></div>{history_html(hist)}</section>'
            f'<section class="wrap block" aria-labelledby="h-mo"><div class="sec-head"><h2 id="h-mo">More offers</h2></div>'
            f'<ul class="links">{"".join(more)}</ul></section>')
    title = fit_title([f"{name}, {cap(o)}" + ("" if live else " (ended)"), name + ("" if live else " (ended)"),
                       f"{who(o)} offer"])
    desc = (f"{name}, {cap(o)}. {cards_text(o)}. {validity_text(o)}. The exact terms, checked {fmt_day(o.checked_at.astimezone(IST).date())}."
            if live else f"Record of a {'movie' if o.is_movie else 'live event'} ticket offer that is no longer shown: {name}, {cap(o)}.")
    key = facts([o]) + json.dumps(hist, sort_keys=True) + status
    og = og_offer(o) if live else None
    return Page(path, title, desc, h1, answer, body, crumbs, stamp_kind, o.checked_at, key + alt, noindex=not live, og=og,
                css=OFFER_CSS + PLAN.BP_CSS + GONE_CSS, extra_ld=[offer_ld(site, o, name, desc_short)] if live else [],
                js=PLAN.page_js([o]) + ICS_JS if live else PLAN.page_js([], {o.id: o.raw}),
                hero=cd_pill(o, today) if live else f'<p class="gone-badge">{E(badge)}</p>')


GONE_CSS = ('.gone-badge{display:inline-block;margin:0 0 var(--s-2);padding:4px 12px;border-radius:var(--r-pill);'
            'background:var(--note-bg);color:var(--note-text);font-weight:700;font-size:var(--t-sm)}')


def alternatives_section(site: "Site", o: Offer) -> str:
    """Current offers that replace a gone one: the same bank first, then the same app. Shown offers only."""
    live = [x for x in site.offers if x.id != o.id and x.is_movie]
    bank = sorted([x for x in live if o.is_bank and x.is_bank and bank_id(x.issuer) == bank_id(o.issuer)], key=lambda x: (-cap_num(x), x.id))
    app = sorted([x for x in live if x.platform == o.platform and x not in bank], key=lambda x: (-cap_num(x), x.id))
    picks = (bank + app)[:4]
    if picks:
        li = "".join(f'<li><a href="{offer_path(x.id)}">{E(who(x))} on {E(where(x))}: {E(what(x))}, {E(cap(x))}</a> · '
                     f'checked {E(check_day(x))}</li>' for x in picks)
        inner = f'<ul class="plain">{li}</ul>'
    else:
        inner = '<p class="log-one">No checked offer from the same bank or on the same app right now. <a href="/">See every offer that passes our checks</a>.</p>'
    links = (f'<li><a href="/bank/{o.slug}/">All {E(site.bank_name(o.issuer))} offers</a></li>'
             if o.is_bank and any(s_ == o.slug for s_, _ in site.banks) else "")
    k = app_key(o.platform)
    if k and any(p == hub_path(k) for p, _ in site.apps):
        links += f'<li><a href="{hub_path(k)}">All {E(APPS[k][1])} offers</a></li>'
    return (f'<section class="wrap block" aria-labelledby="h-alt"><div class="sec-head"><h2 id="h-alt">Current offers instead</h2>'
            f'<p class="meta">Same bank first, then the same app</p></div>{inner}'
            + (f'<ul class="links">{links}</ul>' if links else "") + '</section>')


def offer_pages(site: "Site", offers: list, changes: list, hist_dir: Path, today: date, warn: list, state: dict) -> list:
    """Live pages for every shown offer, and history pages for every offer that had one and is gone or held."""
    pages = [page_offer(site, o, changes, today, warn, freshness_status(o, site.now)) for o in offers]
    live = {o.id for o in offers}
    gone = {i: v for i, v in last_published(hist_dir, site.cfg).items() if i not in live}
    for oid, (raw, day) in sorted(gone.items()):
        o = norm(raw)
        if o.checked_at is None:
            continue
        removed = [c for c in offer_history(oid, changes) if c["type"] == "removed"]
        status = "expired" if o.valid_to and o.valid_to < today else "withdrawn"
        pages.append(page_offer(site, o, changes, today, warn, status, removed[0]["date"] if removed else day))
    known = {p.path for p in pages}
    for path in sorted(p for p in state if p.startswith("/offer/") and p not in known):
        warn.append(f"{path}: had a page but no snapshot holds its record; kept as a stub")
        stub = Page(path, "Offer no longer shown · FDFS", "A movie ticket offer that is no longer shown.",
                    "This offer is no longer shown", '<strong>We no longer show this offer.</strong> See the '
                    '<a href="/">offers that pass our checks</a> and the <a href="/changes/">change log</a>.', "",
                    [("Offers", "/"), ("Changes", "/changes/"), ("No longer shown", path)], "Updated", site.now, "gone",
                    noindex=True)
        pages.append(stub)
    return pages


def recheck_line(o: Offer, now: datetime) -> str:
    """The bot's wording, exactly (owner, 26 Nov; decision 158): whole elapsed days, minimum 1."""
    n = max(1, (now - o.checked_at).days)
    return f"Checked {n} day{'s' if n != 1 else ''} ago · check terms first"


def freshness_status(o: Offer, now: datetime) -> str:
    f = freshness(o, now)
    return "needs_recheck" if f == "needs_recheck" else "current"


def page_changes(changes: list, stamp: datetime) -> Page:
    items = "".join(f'<li class="log-i" id="c-{E(c["date"])}-{E(c["id"])}"><span class="tag">{E(c["label"])} · {E(fmt_day(_d(c["date"])))}</span>'
                    f'<p>{E(c["text"])}</p><a href="{offer_path(c["id"])}">Offer record</a></li>' for c in changes)
    if changes:
        first = min(c["date"] for c in changes)
        added = sum(1 for c in changes if c["type"] in ("first_check", "added"))
        other = len(changes) - added
        answer = (f"<strong>Tracking since {E(fmt_day(_d(first)))}.</strong> {added} offer{'s' if added != 1 else ''} added so far"
                  + (f", {other} other change{'s' if other != 1 else ''}." if other else "."))
    else:
        answer = "<strong>No changes recorded yet.</strong>"
    body = (f'<section class="wrap block"><div class="sec-head"><h2>Every change, newest first</h2>'
            f'<p class="meta"><a href="/changes.xml">Atom feed</a> · <a href="/changes.json">JSON</a></p></div>'
            f'<ol class="log log-1">{items or "<li class=log-i><p>No changes yet.</p></li>"}</ol></section>')
    return Page("/changes/", "Movie ticket offer changes, dated · FDFS",
                "Every new, changed, ended or withdrawn movie ticket offer, dated, from the official terms.",
                "What changed in movie ticket offers?", answer, body, [("Offers", "/"), ("Changes", "/changes/")],
                "Updated", stamp, json.dumps(changes, sort_keys=True))


def page_new_stub(stamp: datetime) -> Page:
    """Only built when data/site.json sets features.new_this_week (off for launch)."""
    prose = "<p>This page will list new releases per city, with language and release date, once we have a source we're allowed to use.</p>"
    p = prose_page("/new-this-week/", "New this week · FDFS", "New releases per city.",
                   "New this week", "<strong>Not available yet.</strong> We don't publish release lists until we have a source we're allowed to use.",
                   prose, "New this week", stamp)
    p.noindex = True
    return p


# ---------------------------------------------------------------- Phase 2 pages (decisions 144-149)
# Real data only. A card page needs >= 1 shown movie offer that LISTS that exact card; a weekday page needs >= 1 shown
# movie offer whose terms name that booking day (a day served only by every-day offers would be a near-duplicate:
# not built); the guide needs >= 1 shown movie offer with a stored quote, and each section needs its own live example.
APP_ORDER = ("bms", "district")          # equal treatment: fixed, alphabetical by app name, the same on every page


def variant_name(v: str) -> str:
    return v.title() if v.isupper() else v


def card_slug(o: Offer, v: str) -> str:
    return f"{o.slug}-{re.sub(r'[^a-z0-9]+', '-', v.lower()).strip('-')}"


def card_path_of(o: Offer, v: str) -> str:
    return f"/card/{card_slug(o, v)}/"


def instrument_word(o: Offer) -> str:
    return {"credit": "Credit Card", "debit": "Debit Card"}.get(o.instrument or "", "Card")


def card_products(offers: list) -> dict:
    """{card slug: {"short", "name", "issuer", "bank_slug", "offers": [...]}} for every exact card product that a shown
    movie offer lists by name. Unstated and all-cards scopes never make a card page (they stay on the bank page)."""
    out: dict = {}
    for o in sorted(offers, key=lambda x: x.id):
        if not (o.is_bank and o.is_movie and o.variants_scope == "listed" and o.variants):
            continue
        for v in o.variants:
            s = card_slug(o, v)
            c = out.setdefault(s, {"short": f"{o.issuer} {variant_name(v)}", "issuer": o.issuer, "bank_slug": o.slug,
                                   "variant": v, "offers": []})
            c["name"] = f"{o.issuer} {variant_name(v)} {instrument_word(o)}"
            c["offers"].append(o)
    # decision 144, anti-doorway: a card page only when its set of offers is its own. Cards of one bank that share the
    # exact same offers (RBL: one offer naming 30 cards) would be the same page with a swapped name; the bank page,
    # which lists every named card, answers those.
    sets: dict = {}
    for s_, c in out.items():
        sets.setdefault((c["bank_slug"], tuple(sorted(o.id for o in c["offers"]))), []).append(s_)
    return {s_: c for s_, c in out.items()
            if len(sets[(c["bank_slug"], tuple(sorted(o.id for o in c["offers"])))]) == 1}


def code_quote(o: Offer, code: str) -> str | None:
    """The quoted span behind one condition: 090's condition_codes first, else the field's own stored quote, and only
    when the field says the condition holds. Never a paraphrase."""
    for c in o.raw.get("condition_codes") or []:
        if isinstance(c, dict) and str(c.get("code", "")).split(":")[0] == code and c.get("quote"):
            return c["quote"]

    def q(k):
        v = o.quotes.get(k)
        v = v[0] if isinstance(v, list) and v else v
        return v if isinstance(v, str) and v.strip() else None
    gate_ = spend_gate(o.quota_note)
    fallback = {
        "booking_day": o.day_basis == "booking" and (q("day_basis") or q("days")),
        "show_day": o.day_basis == "booking" and bool(o.show_days) and q("show_days"),
        "min_tickets": bool(o.min_tickets) and q("min_tickets"),
        "monthly_limit": bool(o.monthly_limit) and q("monthly_limit"),
        "spend_gate": bool(gate_) and q("quota_note"),
        "quota": bool(o.quota_note and not gate_ and re.search(r"\bfirst [\d,]+", o.quota_note, re.I)) and q("quota_note"),
        "app_only": o.channel == "app" and q("channel"),
        "bins": next((q(k) for k in o.quotes if k.startswith("conditions:bins:")), None),
    }.get(code)
    return fallback or None


def deciding_clause(o: Offer) -> tuple[str, str] | None:
    """The clause that decides whether the offer works for you, quoted: the booking day, the minimum, the spend gate,
    the monthly limit, the quota; else the benefit itself. (label, quote)"""
    for code, label in (("booking_day", "Booking day"), ("min_tickets", "Minimum tickets"), ("spend_gate", "Spend rule"),
                        ("monthly_limit", "Monthly limit"), ("quota", "Quota")):
        q = code_quote(o, code)
        if q:
            return label, q
    q = quote_for(o)
    return ("The benefit", q) if q else None


def check_day(o: Offer) -> str:
    return fmt_day(o.checked_at.astimezone(IST).date())


def mini_receipt(site: "Site", o: Offer, today: date, card_link: str = "") -> str:
    """One offer on a card or weekday page: the benefit, the facts that decide it, the quoted clause, the dated check."""
    rows = [("Benefit", f"{what(o)} · {where(o)}"), ("Cap", cap(o)), ("Days", days_plain(o)),
            ("Booking or show day", basis_text(o)), ("Minimum tickets", min_text(o)), ("Monthly limit", limit_text(o))]
    g = spend_gate(o.quota_note)
    if g:
        rows.append(("Spend rule", g))
    rows.append(("Valid", validity_text(o)))
    dl = "".join(f'<div class="rc-r"><dt>{E(k)}</dt><dd>{E(v)}</dd></div>' for k, v in rows)
    dc = deciding_clause(o)
    quote = (f'<blockquote class="o-quote"><p>“{E(dc[1])}”</p><cite>{E(dc[0])}, in the terms · '
             f'{ext(o.source_url, E(domain(o.source_url)))}</cite></blockquote>') if dc else ""
    links = [f'<a href="{offer_path(o.id)}">Every term and the history</a>']
    if any(s == o.slug for s, _ in site.banks):
        links.append(f'<a href="/bank/{o.slug}/">All {E(site.bank_name(o.issuer))} offers</a>')
    if card_link:
        links.append(card_link)
    return (f'<div class="receipt" id="{E(o.id)}"{fresh_attrs(o)}><p class="rc-h"><span>{E(who(o))}</span><span>{E(app_name(o))}</span></p>'
            f'<dl class="rc">{dl}</dl>{quote}'
            f'<p class="rc-f">Checked by {E(checked_by(o, site.cfg))} · <time datetime="{iso(o.checked_at)}">{E(fmt_stamp(o.checked_at))}</time>'
            f' · Terms: {ext(o.source_url, E(domain(o.source_url)) + icon("out"), sr="official terms")}</p>'
            f'<p class="rc-f rc-l">{" · ".join(links)}</p></div>')


def fit_title_n(cands: list[str], n: int) -> str:
    """Like fit_title, but measured as the escaped <title> (an "&" costs 5), the way the title guard measures it."""
    for c in cands:
        if len(E(f"{c} · FDFS")) <= n:
            return f"{c} · FDFS"
    return cands[-1][:n - 7].rstrip() + " · FDFS"


CARD_TITLE_MAX = 65     # the site-wide title guard; the full owner pattern is tried first, then shorter forms (decision 144)


def page_card(site: "Site", slug: str, c: dict, offers: list, today: date) -> Page:
    path = f"/card/{slug}/"
    mine = sorted(c["offers"], key=lambda o: (APP_ORDER.index(o.platform) if o.platform in APP_ORDER else 9, -cap_num(o), o.id))
    stamp = stamp_of(mine)
    d, dm = fmt_day(stamp.astimezone(IST).date()), fmt_dm(stamp.astimezone(IST).date())
    short, name, issuer = c["short"], c["name"], c["issuer"]
    by_app = {k: [o for o in mine if o.platform == k] for k in APP_ORDER}
    others = [o for o in mine if o.platform not in APP_ORDER]
    same_bank = [o for o in offers if o.is_bank and o.is_movie and o.slug == c["bank_slug"] and o not in mine]
    all_cards = [o for o in same_bank if o.variants_scope == "all"]
    maybe = [o for o in same_bank if o.variants_scope == "unstated"]
    n = len(mine)
    parts = []
    for o in mine:
        g = gate_short(o, today)
        extra = f" ({g})" if g else (f" ({times(o.monthly_limit).lower()})" if o.monthly_limit else "")
        parts.append(f"on {where(o)}, {what(o)}, {cap(o)}{extra}")
    none_on = [APPS[k][1] for k in APP_ORDER if not by_app[k]]
    answer = (f"<strong>Yes: {n} checked movie offer{'s' if n != 1 else ''} for the {E(name)}</strong>, {E('; '.join(parts))}."
              + (f" On {E(join_and(none_on))}: no checked offer for this card on {d}." if none_on else ""))
    # each app gets the same block, in the same order, whether or not it has an offer
    secs = ""
    for k in APP_ORDER:
        app = APPS[k][1]
        inner = ("".join(mini_receipt(site, o, today) for o in by_app[k]) if by_app[k] else
                 f'<p class="log-one">No checked {E(app)} offer names the {E(name)} on {E(d)}.'
                 + (f' See <a href="{hub_path(k)}">every {E(app)} offer</a>.' if any(p == hub_path(k) for p, _ in site.apps) else "")
                 + "</p>")
        secs += (f'<section class="wrap block" aria-labelledby="h-{k}"><div class="sec-head"><h2 id="h-{k}">On {E(app)}</h2>'
                 f'<p class="meta">{len(by_app[k])} checked offer{"s" if len(by_app[k]) != 1 else ""}</p></div>'
                 f'<div class="rc-grid">{inner}</div></section>')
    if others:
        secs += ('<section class="wrap block" aria-labelledby="h-oth"><div class="sec-head"><h2 id="h-oth">At cinemas</h2></div>'
                 f'<div class="rc-grid">{"".join(mini_receipt(site, o, today) for o in others)}</div></section>')
    also = ""
    for o in all_cards:
        also += (f'<li><a href="{offer_path(o.id)}">{E(who(o))} on {E(where(o))}: {E(what(o))}, {E(cap(o))}</a>. '
                 f'The terms say all {E(issuer)} credit cards, so this card too. Checked {E(check_day(o))}.</li>')
    for o in maybe:
        also += (f'<li><a href="{offer_path(o.id)}">{E(who(o))} on {E(where(o))}: {E(what(o))}, {E(cap(o))}</a>. '
                 f'The terms say "select {E(issuer)} credit cards" and don\'t list which: check yours is included. '
                 f'Checked {E(check_day(o))}.</li>')
    if also:
        secs += (f'<section class="wrap block" aria-labelledby="h-also"><div class="sec-head"><h2 id="h-also">Other {E(issuer)} offers that may cover this card</h2></div>'
                 f'<ul class="plain">{also}</ul></section>')
    sib = [(p, nm) for p, nm, b in site.cards if b == c["bank_slug"] and p != path]
    more = (f'<li><a href="/bank/{c["bank_slug"]}/">All {E(site.bank_name(issuer))} offers</a></li>'
            + "".join(f'<li><a href="{p}">{E(nm)}</a></li>' for p, nm in sib)
            + '<li><a href="/best-card-for-movie-tickets/">Best card for movie tickets</a></li>'
            + (f'<li><a href="{site.guide}">How card offers work</a></li>' if site.guide else ""))
    secs += (f'<section class="wrap block" aria-labelledby="h-mo"><div class="sec-head"><h2 id="h-mo">More</h2></div>'
             f'<ul class="links">{more}</ul></section>')
    title = fit_title_n([f"{short} movie ticket offers: BookMyShow & District (checked {dm})",
                         f"{short} offers: BookMyShow & District (checked {dm})",
                         f"{short} offers: BookMyShow & District ({dm})",
                         f"{short} movie offers (checked {dm})", f"{short} movie ticket offers"], CARD_TITLE_MAX)
    desc = (f"{name}: {n} checked movie ticket offer{'s' if n != 1 else ''}. "
            + " ".join(f"{app_name(o)}: {what(o)}, {cap(o)}" + (f", {times(o.monthly_limit).lower()}" if o.monthly_limit else "") + "."
                       for o in mine)
            + (f" {join_and(none_on)}: none checked." if none_on else "") + f" From the bank's terms, checked {d}.")
    items = [{"@type": "ListItem", "position": i + 1, "name": f"{who(o)} on {where(o)}: {what(o)}, {cap(o)}",
              "url": site.base + offer_path(o.id)} for i, o in enumerate(mine)]
    key = facts(mine + all_cards + maybe) + json.dumps(sib) + "".join(key_condition(o, today) for o in mine)
    # one offer: its benefit is the fact; several: how many and where (decision 158)
    og = og_hub(f"card-{slug}", name, mine,
                " · ".join(og_benefit(mine[0]) + [app_name(mine[0])]) if n == 1 else "")
    h1 = f"{E(short)} movie ticket offers, <em>by app.</em>"
    return Page(path, title, desc, h1, answer, secs,
                [("Offers", "/"), (f"{site.bank_name(issuer)} offers", f"/bank/{c['bank_slug']}/"), (name, path)],
                "Checked", stamp, key, og=og, css=OFFER_CSS + P2_CSS,
                extra_ld=[{"@type": "ItemList", "name": f"{name} movie ticket offers", "itemListElement": items}])


def weekday_sets(offers: list) -> dict:
    """{day key: offers whose terms name that booking day} for days with >= 1; every-day offers are listed with them."""
    movie = [o for o in offers if o.is_movie]
    return {k: [o for o in movie if k in day_keys(o)] for k in DAY_IDX if any(k in day_keys(o) for o in movie)}


def day_path(k: str) -> str:
    return f"/offers-on/{DAY[k].lower()}/"


def page_weekday(site: "Site", k: str, named: list, offers: list, today: date, warn: list) -> Page:
    day = DAY[k]
    path = day_path(k)
    movie = [o for o in offers if o.is_movie]
    every = sorted([o for o in movie if "any" in o.days], key=lambda o: (-cap_num(o), o.id))
    named = sorted(named, key=lambda o: (-cap_num(o), o.id))
    unstated = sorted([o for o in movie if not day_keys(o) and "any" not in o.days], key=lambda o: o.id)
    stamp = stamp_of(named + every)
    d = fmt_day(stamp.astimezone(IST).date())
    total = len(named) + len(every)
    nb = [o for o in named if o.day_basis == "booking"]
    ns = [o for o in named if o.day_basis == "show"]
    bits = []
    if nb:
        bits.append(f"{len(nb)} only when you book on a {day} (" + "; ".join(
            f"{who(o)}, {what(o)} {cap(o)}" + (", the show can be any day" if "any" in o.show_days else "") for o in nb) + ")")
    if ns:
        bits.append(f"{len(ns)} only for {day} shows (" + "; ".join(f"{who(o)}, {what(o)} {cap(o)}" for o in ns) + ")")
    rest = [o for o in named if o not in nb and o not in ns]
    if rest:
        bits.append(f"{len(rest)} on {day}s, the terms don't say whether the booking or the show day counts")
    if every:
        bits.append(f"{len(every)} that work{'s' if len(every) == 1 else ''} every day")
    answer = (f"<strong>{total} checked movie offer{'s' if total != 1 else ''} work on a {day}</strong>, checked {d}: {E('; '.join(bits))}."
              + (f" {len(unstated)} more don't state any days." if unstated else ""))
    explain = (f'<section class="wrap block" aria-labelledby="h-bs"><div class="sec-head"><h2 id="h-bs">Booking day or show day?</h2></div>'
               f'<div class="prose"><p>Terms count one of two days. <strong>Booking day</strong>: the day you pay. '
               f'<strong>Show day</strong>: the day the film plays. A "book on a {day}" offer works for a show on another day, '
               f'and a "{day} shows" offer works if you book earlier. Each row says which day its terms count.</p></div></section>')
    rows = [[f'<a href="{offer_path(o.id)}">{E(who(o))}</a>', E(where(o)), E(what(o)), E(cap(o)), E(basis_text(o)),
             E(key_col(o, today)), ext(o.source_url, E(domain(o.source_url)))] for o in named + every]
    tbl = table(rows, ["Card or pass", "Where", "Benefit", "Cap", "Which day counts", "Key condition", "Terms"],
                f"Movie offers that work on a {day}, checked {fmt_stamp(stamp)}", named + every)
    body = (f'<section class="wrap block" aria-labelledby="h-cmp"><div class="sec-head"><h2 id="h-cmp">Every offer that works on a {day}</h2>'
            f'<p class="meta">{day}-only first, then every day; highest cap first</p></div>{tbl}</section>' + explain
            + f'<section class="wrap block" aria-labelledby="h-only"><div class="sec-head"><h2 id="h-only">Only on {day}s</h2></div>'
            f'<div class="grid">{"".join(offer_card(site, o, today, warn, path) for o in named)}</div></section>')
    if unstated:
        body += (f'<section class="wrap block" aria-labelledby="h-un"><div class="sec-head"><h2 id="h-un">Days not stated</h2></div>'
                 f'<p class="log-one">These terms name no days, so they may work on a {day} too. Read them before you book.</p><ul class="plain">'
                 + "".join(f'<li><a href="{offer_path(o.id)}">{E(who(o))} on {E(where(o))}: {E(what(o))}, {E(cap(o))}</a></li>'
                           for o in unstated) + "</ul></section>")
    body += related_links(site, path)
    title = fit_title([f"Movie ticket offers that work on {day}", f"Offers that work on {day}"])
    desc = (f"{total} movie ticket offers that work on a {day}, checked {d}: "
            + "; ".join(f"{who(o)}, {what(o)} {cap(o)}" + (" (book on a " + day + ")" if o in nb else "") for o in named)
            + (f"; plus {len(every)} every-day offer{'s' if len(every) != 1 else ''}." if every else ".")
            + " Booking day and show day, said plainly.")
    items = [{"@type": "ListItem", "position": i + 1, "name": f"{who(o)} on {where(o)}: {what(o)}, {cap(o)}",
              "url": site.base + offer_path(o.id)} for i, o in enumerate(named + every)]
    key = facts(named + every + unstated) + "".join(key_col(o, today) for o in named + every)
    return Page(path, title, desc, f"Movie ticket offers that work on <em>{day}.</em>", answer, body,
                [("Offers", "/"), (f"Offers on {day}", path)], "Checked", stamp, key,
                og=og_hub(f"day-{day.lower()}", f"{day} movie offers", named + every),
                extra_ld=[{"@type": "ItemList", "name": f"Movie ticket offers that work on {day}", "itemListElement": items}])


GUIDE_PATH = "/guide/how-movie-card-offers-work/"


def guide_example(o: Offer, q: str) -> str:
    return (f'<blockquote class="o-quote"><p>“{E(q)}”</p><cite>{E(who(o))} on {E(where(o))} · '
            f'<a href="{offer_path(o.id)}">the offer</a> · Checked {E(check_day(o))} · '
            f'{ext(o.source_url, E(domain(o.source_url)))}</cite></blockquote>')


def first_span(o: Offer, k: str) -> str | None:
    """One verbatim span for a field (a field may be backed by several; the guide quotes one, never a joined string)."""
    v = o.quotes.get(k)
    for x in (v if isinstance(v, (list, tuple)) else [v]):
        if isinstance(x, str) and x.strip():
            return x
    return None


def guide_sections(site: "Site", offers: list) -> list:
    """[(id, question, answer html)] - a section only when a live offer gives it a real, quoted example."""
    movie = sorted([o for o in offers if o.is_movie and o.quotes], key=lambda o: o.id)
    out = []

    used: set = set()

    def ex(pairs, n=2):
        """Up to n examples, preferring quotes no earlier section has shown (each quote once on the page if possible)."""
        pairs = [(o, q) for o, q in pairs if q]
        pairs = [x for x in pairs if x[1] not in used] + [x for x in pairs if x[1] in used]
        seen, html_ = set(), ""
        for o, q in pairs:
            if q not in seen and len(seen) < n:
                seen.add(q)
                used.add(q)
                html_ += guide_example(o, q)
        return html_
    bogo = [o for o in movie if o.kind == "bogo"]
    if bogo:
        out.append(("bogo", "How does buy 1 get 1 on movie tickets work?",
                    "<p>You buy two tickets in one booking with the named card, and the app takes the price of one ticket off, "
                    "up to the cap. If the ticket costs more than the cap, you pay the difference. The terms we've read don't "
                    "say a third or fourth ticket is free.</p>" + ex([(o, first_span(o, "value") or first_span(o, "kind")) for o in bogo])))
    pt = [o for o in movie if o.raw.get("cap_type") == "per_ticket"]
    pm = [o for o in movie if o.raw.get("cap_type") == "per_month"]
    if pt or pm:
        out.append(("caps", "What does \"up to ₹…\" mean?",
                    "<p>The cap is the most the bank takes off. Some terms cap each free ticket; others cap the whole month. "
                    "Read which: a monthly cap can run out in one booking.</p>"
                    + ex([(o, first_span(o, "value")) for o in pt], 1) + ex([(o, first_span(o, "value")) for o in pm], 1)))
    mt = [(o, code_quote(o, "min_tickets")) for o in movie if code_quote(o, "min_tickets")]
    if mt:
        out.append(("min", "Do I need to buy 2 tickets?",
                    "<p>For a 2nd-ticket offer, yes: both tickets must be in the same booking. Some terms say so outright.</p>" + ex(mt)))
    ml = [(o, code_quote(o, "monthly_limit")) for o in movie if code_quote(o, "monthly_limit")]
    if ml:
        cal = [(o, q) for o, q in ml if "calendar month" in q.lower()]
        out.append(("monthly", "How many times a month can I use it, and when does it reset?",
                    "<p>Terms often limit each card to a number of uses a month. \"Calendar month\" means the count starts again "
                    "on the first day of each month, not a rolling month from your last booking. Where the terms only say \"a month\", they don't say "
                    "when it resets.</p>" + ex(cal + [x for x in ml if x not in cal])))
    qu = [(o, code_quote(o, "quota")) for o in movie if code_quote(o, "quota")]
    if qu:
        out.append(("quota", "Why does it say the offer is over when I have the card?",
                    "<p>Some offers stop after a fixed number of users or bookings, for the day or the month. Once that count "
                    "is reached, the offer stops for everyone until it resets, even with the right card.</p>" + ex(qu)))
    bd = [(o, code_quote(o, "booking_day")) for o in movie if code_quote(o, "booking_day")]
    sd = [(o, code_quote(o, "show_day")) for o in movie if code_quote(o, "show_day")]
    if bd or sd:
        out.append(("days", "Does the booking day or the show day count?",
                    "<p>It depends on the wording. \"Booked on a Saturday\" means the day you pay; the show can be later. "
                    "\"Shows on a Saturday\" means the day the film plays. If the terms say neither, we mark the days as not stated."
                    + "".join(f' See <a href="{pth}">{E(lab)}</a>.' for pth, lab in site.days) + "</p>"
                    + ex(bd + sd, 3)))
    fails = []
    sg = [(o, code_quote(o, "spend_gate")) for o in movie if code_quote(o, "spend_gate")]
    if sg:
        fails.append(("A minimum spend first", "The card must have spent a set amount in earlier months.", sg))
    ao = [(o, code_quote(o, "app_only")) for o in movie if code_quote(o, "app_only")]
    if ao:
        fails.append(("App only", "Booking on the website doesn't count.", ao))
    cq = [(o, first_span(o, "code")) for o in movie if o.code and first_span(o, "code")]
    if cq:
        fails.append(("A code to apply", "Without the code, the price stays the same.", cq))
    bq = [(o, code_quote(o, "bins")) for o in movie if code_quote(o, "bins")]
    if bq:
        fails.append(("Only some card numbers", "Only cards whose first digits (the BIN) are listed qualify.", bq))
    if qu:
        fails.append(("The quota ran out", "Later bookers miss out until it resets.", qu[:1]))
    if ml:
        fails.append(("This month's uses are spent", "The card has already used its limit this month.", ml[:1]))
    if fails:
        out.append(("fail", "Why did my card offer fail at checkout?",
                    "<p>These are the reasons the terms we've checked give, each with a real example.</p>" + "".join(
                        f"<h3>{E(h)}</h3><p>{E(t)}</p>" + ex(p, 1) for h, t, p in fails)))
    fp = [(o, first_span(o, "conditions:full_payment_on_card")) for o in movie if first_span(o, "conditions:full_payment_on_card")]
    nw = [(o, first_span(o, "conditions:no_wallet")) for o in movie if first_span(o, "conditions:no_wallet")]
    if fp or nw:
        out.append(("wallet", "Can I pay partly with a wallet or another card?",
                    "<p>Not where the terms exclude it. Some say the whole amount must go on the named card, and that paying "
                    "with the card through a wallet doesn't count.</p>" + ex(fp[:1] + nw[:1])))
    return out


def page_guide(site: "Site", offers: list, now: datetime) -> Page | None:
    secs = guide_sections(site, offers)
    if not secs:
        return None
    toc = "".join(f'<li><a href="#g-{i}">{E(q)}</a></li>' for i, q, _ in secs)
    prose = "".join(f'<h2 id="g-{i}">{E(q)}</h2>{a}' for i, q, a in secs)
    n = len({o.id for o in offers if o.is_movie})
    answer = (f"<strong>A card offer works only if every condition in its terms holds:</strong> the card, the app, the day, "
              f"the number of tickets, this month's uses and the quota. Below, each rule with real quotes from the "
              f"{n} offers that pass our checks, each dated.")
    body = (f'<section class="wrap block" aria-labelledby="h-toc"><div class="sec-head"><h2 id="h-toc">Questions</h2></div>'
            f'<ol class="plain toc">{toc}</ol></section>'
            f'<section class="wrap block"><div class="prose guide">{prose}</div></section>'
            '<section class="wrap block"><div class="prose"><p>Every quote above is from a bank\'s own terms page, read and '
            're-read by us; each links to its offer and shows the date we checked it. <a href="/how-we-check/">How we check</a> · '
            '<a href="/best-card-for-movie-tickets/">Best card for movie tickets</a></p></div></section>')
    key = prose + answer
    return Page(GUIDE_PATH, fit_title(["How card offers on movie tickets work", "How movie card offers work"]),
                "Caps, minimum tickets, monthly limits and resets, booking day vs show day, and why card offers fail at "
                "checkout, each with a quote from the live terms and the date we checked it.",
                "How card offers on movie tickets <em>work.</em>", answer, body,
                [("Offers", "/"), ("How card offers work", GUIDE_PATH)], "Updated", now, key, css=P2_CSS)


P2_CSS = ('.rc-grid{display:grid;gap:var(--s-4)}.rc-grid .receipt{max-width:none}.rc-l{font-weight:600}'
          '.toc{counter-reset:q;display:grid;gap:6px}.guide h3{font:700 var(--t-md)/1.3 var(--font-display);margin:var(--s-4) 0 var(--s-1)}'
          '@media (min-width:900px){.rc-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}')


# ---------------------------------------------------------------- OG cards
# Decision 158 (owner, 26 Nov): one idea per card, big enough to read in a WhatsApp preview. The benefit (or the
# page's subject) is the hero, one smaller line says card and app (or one fact from the data), and the foot is a
# small mark + bookmyfdfs.in. Offer cards alone carry one quiet date. No "checked against the official terms"
# headline, no checker/time line and no "Independent" strip: those stay on the pages.
OG_INK, OG_IVORY, OG_LIME = "#203229", "#F6F5EE", "#D5F476"
OG_W = 1056                     # 72 px gutters on a 1200 px card
OG_HERO, OG_SUB = 104, 44       # px; the render step shrinks a line that is still too wide (never grows it)


def og_est(text: str, px: float, display: bool = False) -> float:
    """Rough rendered width, only to choose wrapping; the browser's own measurement is the real overflow guard."""
    em = 0.54 if display else 0.52
    return sum((0.3 if ch == " " else 0.62 if ch.isupper() or ch in "₹%" else em) for ch in text) * px


def og_wrap(text: str, px: float, display: bool = False, max_lines: int = 2) -> list:
    """Greedy wrap on words into at most max_lines lines; a ' · ' break is preferred when the text has one."""
    if og_est(text, px, display) <= OG_W:
        return [text]
    if " · " in text and max_lines >= 2:
        head, tail = text.split(" · ", 1)
        if og_est(head, px, display) <= OG_W and og_est(tail, px, display) <= OG_W:
            return [head, tail]
    words = text.split(" ")
    if display and max_lines == 2 and len(words) > 1:   # a headline breaks into two balanced lines, no orphan word
        i = min(range(1, len(words)), key=lambda k: max(og_est(" ".join(words[:k]), px, True),
                                                        og_est(" ".join(words[k:]), px, True)))
        return [" ".join(words[:i]), " ".join(words[i:])]
    lines = [""]
    for w in words:
        t = (lines[-1] + " " + w).strip()
        if og_est(t, px, display) <= OG_W or not lines[-1] or len(lines) == max_lines:
            lines[-1] = t
        else:
            lines.append(w)
    return lines


def og_and(items: list) -> str:
    items = list(dict.fromkeys(items))
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " & " + items[-1]


def og_apps(offers: list) -> str:
    return og_and(sorted({app_name(o) for o in offers}, key=lambda a: (a != "BookMyShow", a)))


def og_count(offers: list) -> str:
    n = len(offers)
    kind = "card" if offers and all(o.is_bank for o in offers) else "movie"
    return f"{n} {kind} offer{'s' if n != 1 else ''}"


def og_card_line(o: Offer) -> str:
    """'HSBC Premier Mastercard · BookMyShow'. A long listed-cards name is counted, never cut: 'RBL Bank · 6 listed cards'."""
    line = f"{who(o)} · {app_name(o)}"
    if og_est(line, OG_SUB) > OG_W and o.variants_scope == "listed" and len(o.variants) > 1:
        line = f"{o.issuer} · {len(o.variants)} listed cards · {app_name(o)}"
    return line


def og_benefit(o: Offer) -> list:
    """['2nd ticket free', 'up to ₹750']: the benefit and its cap, as the terms state them."""
    c = cap(o)
    return [what_full(o)] + ([c] if c != "cap: see terms" else [])


def og_spec(name: str, hero: list, sub: str, ids: list, date_: str = "", benefit: bool = False, alt_sub: str = "") -> dict:
    """hero: 1-2 big lines; sub: one fact; date_: offer cards only. 'lines' is the alt text.
    One lime line per card: a benefit's last hero line (the cap, or the benefit alone), else the fact line."""
    head = " · ".join(hero)
    if len(hero) == 1:        # one line if it reads at >= 88 px, else two lines at full size
        hero = [hero[0]] if og_est(hero[0], 88, display=True) <= OG_W else og_wrap(hero[0], OG_HERO, display=True)
    subs = og_wrap(sub, OG_SUB)
    return {"name": name, "hero": hero[:2], "accent": benefit, "sub": subs[:2], "date": date_, "ids": ids,
            "lines": [head, alt_sub or sub] + ([date_] if date_ else [])}


def og_offer(o: Offer) -> dict:
    return og_spec(f"offer-{offer_slug(o.id)}", og_benefit(o), og_card_line(o), [o.id],
                   f"Checked {fmt_dm(o.checked_at.astimezone(IST).date())}", benefit=True, alt_sub=f"{who(o)} · {app_name(o)}")


def og_hub(name: str, title: str, movie: list, fact: str = "") -> dict:
    """Home, app, bank, weekday and best-card pages: the subject plus one fact from the page's own offers."""
    if not fact:
        fact = f"{og_count(movie)} · {og_apps(movie)}" if movie else "No movie offer passes our checks"
    return og_spec(name, [title], fact, [o.id for o in movie])


def og_alt(lines: list) -> str:
    return ". ".join(l.rstrip(":,. ") for l in lines if l.strip()) + "."


OG_FIT_JS = ("<script>document.fonts.ready.then(function(){"
             "var g={};[].forEach.call(document.querySelectorAll('text[data-fit]'),function(t){"
             "var w=+t.getAttribute('data-w'),s=+t.getAttribute('font-size'),k=t.getAttribute('data-fit');"
             "while(t.getComputedTextLength()>w&&s>10){s-=2;t.setAttribute('font-size',s)}"
             "g[k]=Math.min(g[k]||1e9,s)});"
             "[].forEach.call(document.querySelectorAll('text[data-fit]'),function(t){"
             "t.setAttribute('font-size',g[t.getAttribute('data-fit')])});document.body.setAttribute('data-fit','done')})</script>")


def og_svg(site: Site, spec: dict) -> str:
    """1200x630 share card on the ink stage. Text only from the page's own numbers and dates; never 'today'.
    Every line carries data-fit/data-w: the render step (OG_FIT_JS) shrinks a line group until it fits."""
    hero, subs, date_ = spec["hero"], spec["sub"], spec.get("date", "")
    hs = OG_HERO if len(hero) == 2 else OG_HERO + 12
    # vertical centring of hero + sub between the top edge and the foot (y 470)
    block = hs * 0.78 + (len(hero) - 1) * hs * 1.04 + 36 + len(subs) * OG_SUB * 1.3
    y = round(70 + (430 - block) / 2 + hs * 0.78)
    out = []
    for i, t in enumerate(hero):
        fill = OG_LIME if (spec.get("accent") and i == len(hero) - 1) else OG_IVORY
        out.append(f'<text x="72" y="{y}" class="t" font-size="{hs}" fill="{fill}" data-fit="hero" data-w="{OG_W}">{E(t)}</text>')
        y += round(hs * 1.04)
    y += 36 - round(hs * 1.04) + round(OG_SUB * 1.3)
    for t in subs:
        tone = f'fill="{OG_IVORY}" fill-opacity=".86"' if spec.get("accent") else f'fill="{OG_LIME}"'   # one lime line per card
        out.append(f'<text x="72" y="{y}" class="b" font-size="{OG_SUB}" {tone} '
                   f'data-fit="sub" data-w="{OG_W}">{E(t)}</text>')
        y += round(OG_SUB * 1.3)
    seats = "".join(f'<path fill="{OG_LIME if i == 3 else OG_IVORY}" d="{d}"/>' for i, d in enumerate(site.mb["seats"]))
    letters = f'<g fill="{OG_INK}">{"".join(site.mb["letters"])}</g>'
    stamp = (f'<text x="1128" y="566" text-anchor="end" class="b" font-size="28" fill="{OG_IVORY}" fill-opacity=".6">'
             f'{E(date_)}</text>') if date_ else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
<defs><style>.t{{font-family:"Bricolage Grotesque",Arial,sans-serif;font-weight:700;letter-spacing:-0.025em}}.b{{font-family:"Google Sans",Arial,sans-serif;font-weight:500}}</style></defs>
<rect width="1200" height="630" fill="{OG_INK}"/>
<rect x="72" y="64" width="72" height="8" rx="4" fill="{OG_LIME}"/>
{"".join(out)}
<g transform="translate(72 527) scale(0.78)">{seats}{letters}</g>
<text x="128" y="566" class="b" font-size="30" fill="{OG_IVORY}">bookmyfdfs.in</text>
{stamp}
</svg>'''


def chrome_path():
    import os
    for c in (os.environ.get("FDFS_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    return None


def og_stage(root: Path, specs: list, site: Site, extra: str = "") -> Path:
    """A temp folder with one HTML page per card (fonts + the fit script). extra: appended script (tests measure with it)."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "fonts").mkdir()
    for f in ("bricolage-latin.woff2", "bricolage-rupee.woff2", "google-sans-latin.woff2", "google-sans-rupee.woff2"):
        shutil.copyfile(root / "assets/fonts" / f, tmp / "fonts" / f)
    css = ('<style>@font-face{font-family:"Bricolage Grotesque";src:url(fonts/bricolage-latin.woff2);font-weight:600 800}'
           '@font-face{font-family:"Bricolage Grotesque";src:url(fonts/bricolage-rupee.woff2);unicode-range:U+20B9;font-weight:600 800}'
           '@font-face{font-family:"Google Sans";src:url(fonts/google-sans-latin.woff2);font-weight:400 700}'
           '@font-face{font-family:"Google Sans";src:url(fonts/google-sans-rupee.woff2);unicode-range:U+20B9;font-weight:400 700}'
           'html,body{margin:0;background:#203229}</style>')
    for s in specs:
        (tmp / f"{s['name']}.html").write_text("<!doctype html><meta charset=utf-8>" + css + og_svg(site, s) + OG_FIT_JS + extra,
                                               encoding="utf-8")
    return tmp


def render_og_pngs(root: Path, specs: list, out_dir: Path, site: Site) -> bool:
    """Rasterise each card with headless Chrome (optional build step). Returns False if it can't."""
    import http.server
    import subprocess
    import tempfile
    import threading
    ch = chrome_path()
    if not ch:
        return False
    tmp = og_stage(root, specs, site)

    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp), **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ok = True
    try:
        for s in specs:
            dst = out_dir / f"{s['name']}.png"
            for attempt in range(2):  # headless Chrome occasionally hangs: fresh profile, one retry
                prof = tempfile.mkdtemp()
                try:
                    subprocess.run([ch, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                                    f"--user-data-dir={prof}", "--force-device-scale-factor=1",
                                    "--virtual-time-budget=3000", "--window-size=1200,630", f"--screenshot={dst}",
                                    f"http://127.0.0.1:{srv.server_address[1]}/{s['name']}.html"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
                except subprocess.TimeoutExpired:
                    pass
                finally:
                    shutil.rmtree(prof, ignore_errors=True)
                if dst.exists():
                    break
            ok = ok and dst.exists()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


# ---------------------------------------------------------------- build
# Search and AI crawlers, each explicitly allowed (owner, 25 Nov). No Disallow, no Crawl-delay.
CRAWLERS = ("Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User",
            "ClaudeBot", "Claude-SearchBot", "Google-Extended", "Applebot", "Applebot-Extended", "DuckDuckBot")


def site_css(root: Path) -> str:
    tokens = (root / "assets/tokens.css").read_text(encoding="utf-8").replace('url("fonts/', 'url("/assets/fonts/')
    css = tokens + "\n" + (root / "gen/site.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # strip comments
    return re.sub(r"\s*\n\s*", "\n", css).strip() + "\n"  # collapse indentation (no string values span lines)


def content_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# The MCP Registry proves we own bookmyfdfs.in by reading https://bookmyfdfs.in/.well-known/mcp-registry-auth: one line with
# the owner's PUBLIC Ed25519 key (format from modelcontextprotocol.io/registry/authentication). The private key never
# comes near this repo. No file, nothing served; a malformed file stops the build rather than publish a broken proof.
MCP_REGISTRY_AUTH_RX = re.compile(r"v=MCPv1; k=ed25519; p=[A-Za-z0-9+/]{43}=")


def mcp_registry_proof(root: Path) -> str | None:
    f = root / "data/mcp-registry-auth.txt"
    if not f.exists():
        return None
    line = f.read_text(encoding="utf-8").strip()
    if not MCP_REGISTRY_AUTH_RX.fullmatch(line):
        raise ValueError("data/mcp-registry-auth.txt must be one line: v=MCPv1; k=ed25519; p=<base64 public key>")
    return line


def build(data: Path, hist: Path, out: Path, state_path: Path, cfg_path: Path, root: Path = ROOT, snapshot=False,
          render_og=False, spotted=None) -> dict:
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    now, offers_all = load(data)
    meta = {k: v for k, v in json.loads(Path(data).read_text(encoding="utf-8")).items() if k in FEED_TOP}
    today = now.astimezone(IST).date()
    warn: list[str] = []
    offers, held = [], []
    for o in offers_all:
        ok, why = publishable(o, now, cfg)
        (offers if ok else held).append(o)
        if not ok:
            warn.append(f"held back {o.id or '?'}: {why}")
    if snapshot:
        hist.mkdir(parents=True, exist_ok=True)
        snap = hist / f"{today.isoformat()}.json"
        if not snap.exists():
            shutil.copyfile(data, snap)
    changes = changes_from_history(hist, cfg)
    state = json.loads(Path(state_path).read_text(encoding="utf-8")) if Path(state_path).exists() else {}
    banks = sorted({(o.slug, o.issuer) for o in offers if o.is_bank})
    site = Site(root, cfg, now, banks)
    site.meta = meta
    site.og_render = bool(render_og and chrome_path())
    site.css_v = content_hash(site_css(root))[:8]   # cache-busting: a new stylesheet gets a new URL

    spot_old: list = []
    spots, spot_drop = load_spotted(spotted, offers, now, archive=spot_old)
    warn += [f"spotted lead dropped {d}" for d in spot_drop]
    order = list(APPS)
    hub_keys = sorted({app_key(o.platform) for o in offers if o.is_movie and app_key(o.platform)}, key=order.index)
    site.apps = [(hub_path(k), APPS[k][1]) for k in hub_keys]
    for slug, _ in banks:
        ks = sorted({app_key(o.platform) for o in offers if o.is_bank and o.is_movie and o.slug == slug and app_key(o.platform)},
                    key=order.index)
        if len(ks) >= 2:
            site.bank_apps[slug] = ks
    site.plan_offers = offers
    site.plan_gone = {i: r for i, (r, _) in last_published(hist, cfg).items() if i not in {o.id for o in offers}}
    site.offers = offers
    cards = card_products(offers)
    site.cards = [(f"/card/{s_}/", c["name"], c["bank_slug"]) for s_, c in sorted(cards.items())]
    wsets = weekday_sets(offers)
    site.days = [(day_path(k), f"Offers on {DAY[k]}") for k in sorted(wsets, key=DAY_IDX.get)]
    site.guide = GUIDE_PATH if guide_sections(site, offers) else None
    weeks = weekly_pages(site, offers, changes, hist, now, spots)
    site.week = "/this-week/" if any(w.path == "/this-week/" for w in weeks) else None
    # decision 169: a lead "near" a checked offer (same issuer, same app) shows only on /spotted/, with its note; next
    # to the checked offer on home and app pages it would read as a second, unchecked copy of it
    far = [x for x in spots if not x.near]
    pages = [page_home(site, offers, changes, today, warn, far, len(spots))]
    for k in hub_keys:
        pages.append(page_app(site, k, [o for o in offers if app_key(o.platform) == k],
                              [x for x in far if app_key(x.platform) == k], changes, today, warn))
    for slug, ks in site.bank_apps.items():
        for k in ks:
            pages.append(page_bank_app(site, slug, k, [o for o in offers if o.is_bank and o.slug == slug and app_key(o.platform) == k],
                                       today, warn))
    pages += weeks
    bank_pages = [page_bank(site, slug, [o for o in offers if o.is_bank and o.slug == slug], changes, today, warn)
                  for slug, _ in banks]
    # one rule for every bank title: the check date only if it fits (<= 65 chars) on all of them
    opts = [b.title_options for b in bank_pages if b.title_options]
    all_dated = opts and all(len(f"{o[0][0]} · FDFS") <= 65 for o in opts)
    for b in bank_pages:
        if b.title_options:
            # measured as the escaped <title> ("&" costs 5), the way the title guard measures it (decision 174)
            b.title = fit_title_n(b.title_options[0] if all_dated else b.title_options[1], 65)
    pages += bank_pages
    pages += offer_pages(site, offers, changes, hist, today, warn, state)
    best = page_best(site, offers, today)
    if best:
        pages.append(best)
    pages += [page_card(site, s_, c, offers, today) for s_, c in sorted(cards.items())]
    pages += [page_weekday(site, k, wsets[k], offers, today, warn) for k in sorted(wsets, key=DAY_IDX.get)]
    guide = page_guide(site, offers, now)
    if guide:
        pages.append(guide)
    pages += trust_pages(site, offers, now, bool(spots))
    if any(o.is_movie for o in offers):
        pages.append(PLAN.calendar_page(site, offers, today))   # P3, decision 153: real data only
    if spots or spot_old:
        pages.append(page_spotted(spots, now, site.base, spot_old))
    pages.append(page_changes(changes, now))
    if (cfg.get("features") or {}).get("new_this_week", False):  # off for launch: no dead-end pages
        pages.append(page_new_stub(now))

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    og_dir = out / "og"
    og_dir.mkdir()
    shutil.copyfile(root / "brand/logo/og-brand.png", og_dir / "brand.png")
    specs = [{**p.og, "page": ("index.html" if p.path == "/" else p.path.strip("/") + "/index.html")} for p in pages if p.og]
    if site.og_render and not render_og_pngs(root, specs, og_dir, site):
        warn.append("OG rendering failed: every page uses the dateless brand card")
        site.og_render = False
        for s_ in specs:
            (og_dir / f"{s_['name']}.png").unlink(missing_ok=True)
    new_state, changed = {}, []
    for p in pages:
        # not the title or the answer's dates: they carry the check date, which isn't a content change
        h = content_hash(p.content_key + p.h1 + re.sub(r"\b\d{1,2} [A-Z][a-z]{2}(?: \d{4})?\b", "", p.answer))
        old = state.get(p.path)
        same = bool(old and old.get("hash") == h)
        lastmod = old["lastmod"] if same else today.isoformat()
        if p.stamp_kind == "Updated":
            p.stamp = _dt(old["modified"]) if same else now
            for x in p.extra_ld:
                if x.get("@type") == "Dataset":
                    x["dateModified"] = iso(now)
                if x.get("@type") == "Article":
                    x["dateModified"] = iso(p.stamp)
                    x["datePublished"] = iso(min(p.published or p.stamp, p.stamp))
        if not same:
            changed.append(p.path)
        new_state[p.path] = {"hash": h, "lastmod": lastmod, "modified": iso(p.stamp), "noindex": p.noindex}
        html_text = site.render(p)
        check_links(html_text, p.path, urlparse(cfg["base_url"]).hostname.removeprefix("www."))
        if BANNED.search(re.sub(r"<script type=\"application/ld\+json\">.*?</script>", "", html_text)):
            raise SystemExit(f"banned wording on {p.path}: {BANNED.search(html_text).group(0)!r}")
        target = out / p.path.strip("/") / "index.html" if p.path != "/" else out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
    nf = Page("/404.html", "Page not found · FDFS", "This page doesn't exist.", "Page not found",
              '<strong>This page doesn\'t exist.</strong> <a href="/">See the checked offers</a>.', "",
              [("Offers", "/")], "Updated", now, "404", noindex=True, canonical=False)
    nf_html = site.render(nf)
    check_links(nf_html, "/404.html", urlparse(cfg["base_url"]).hostname.removeprefix("www."))
    (out / "404.html").write_text(nf_html, encoding="utf-8")


    # ---- feeds and discovery
    base = cfg["base_url"].rstrip("/")
    sm = "".join(f"<url><loc>{base}{path}</loc><lastmod>{s['lastmod']}</lastmod></url>"
                 for path, s in sorted(new_state.items()) if not s["noindex"])
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                     + sm + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(
        "# FDFS welcomes search engines and AI answer engines.\nUser-agent: *\nAllow: /\n\n"
        + "".join(f"User-agent: {b}\nAllow: /\n\n" for b in CRAWLERS)
        + f"Sitemap: {base}/sitemap.xml\n", encoding="utf-8")
    # decision 167: a version agents and the bot can check (the bot already reads an int schema_version), the count,
    # and each offer's own page. Additive only: no existing key changes.
    pub = {"schema_version": 1, "count": len(offers), "llms_full": base + "/llms-full.txt", "license": "CC-BY-4.0", "license_note": "Quoted terms remain their owners'; the licence covers FDFS's compilation and structure.", "attribution": "FDFS (bookmyfdfs.in)", "source": base + "/",
           "generated_at": now.isoformat(timespec="seconds"), "method": base + "/how-we-check/",
           "offers": [{**{k: o.raw.get(k) for k in ("id", "issuer", "card_variants", "variants_scope", "category", "kind", "value",
                                                     "cap_text", "platform", "channel", "days", "day_basis", "show_days",
                                                     "min_tickets", "monthly_limit", "quota_note", "requires_purchase", "cities",
                                                     "code", "excludes", "valid_from", "valid_to", "source_url", "terms_urls",
                                                     "quotes", "checked_at")},
                       "label": who(o), "checked_by": checked_by(o, cfg), "url": base + offer_path(o.id),
                       "check_method": "manual" if manual_recorded(o) else "automated"}
                      for o in sorted(offers, key=lambda x: x.id)]}
    (out / "offers.json").write_text(json.dumps(pub, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "changes.json").write_text(json.dumps({"license": "CC-BY-4.0", "attribution": "FDFS (bookmyfdfs.in)",
                                                  "changes": changes}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    upd = max((c["at"] for c in changes), default=now.isoformat(timespec="seconds"))
    entries = "".join(
        f'<entry><id>{base}/changes/#c-{c["date"]}-{c["id"]}</id><title>{E(c["label"])}: {E(c["text"].rstrip("."))}</title>'
        f'<updated>{c["at"]}</updated><link href="{base}/changes/#c-{c["date"]}-{c["id"]}"/>'
        f'<summary>{E(c["text"])}</summary></entry>' for c in changes[:50])
    (out / "changes.xml").write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>FDFS · Movie ticket offer changes</title>'
        f'<id>{base}/changes/</id><link href="{base}/changes.xml" rel="self"/><link href="{base}/changes/"/>'
        f'<updated>{upd}</updated><author><name>FDFS</name></author>{entries}</feed>\n', encoding="utf-8")
    # decision 161: each bank line in llms.txt carries that page's own quotable answer (its meta description)
    bank_desc = {p.path: p.desc for p in pages if p.path.startswith("/bank/") and p.path.count("/") == 3 and not p.noindex}
    (out / "llms.txt").write_text(
        f"# FDFS\n\n> FDFS (Film · Deals · Friends · Seats) is an independent site that checks movie ticket offers in India "
        f"against the issuer's official terms. Every fact carries its source link, a verbatim quote and the time it was "
        f"checked (IST). Not affiliated with any ticketing app, cinema or bank.\n\n"
        f"## Key pages\n\n- [Offers]({base}/): every offer that passes our checks\n"
        f"- [Best credit card for movie tickets]({base}/best-card-for-movie-tickets/): grouped by benefit type, with the ordering rule\n"
        + "".join(f"- [{site.bank_name(n)} offers]({base}/bank/{s}/)" + (f": {bank_desc[f'/bank/{s}/']}" if bank_desc.get(f"/bank/{s}/") else "")
                  + "\n" for s, n in banks)
        + "".join(f"- [{n} offers]({base}{pth}): every checked movie offer on {n}, compared\n" for pth, n in site.apps)
        + (f"- [This week]({base}/this-week/): the week's movie ticket offers and what changed, dated\n" if site.week else "")
        + (f"- [Calendar]({base}/calendar/): the next 7 days, which offers to book on which day, booking vs show day, "
           f"monthly limits\n" if any(o.is_movie for o in offers) else "")
        + "".join(f"- [{nm} movie ticket offers]({base}{pth}): that card's checked offers on each app, the deciding clause quoted\n"
                  for pth, nm, _ in site.cards)
        + "".join(f"- [{lab}]({base}{pth}): offers whose terms name that booking day, plus every-day offers\n" for pth, lab in site.days)
        + (f"- [How card offers on movie tickets work]({base}{site.guide}): caps, minimums, monthly limits, booking vs show day, "
           f"why offers fail at checkout, with dated quotes\n" if site.guide else "")
        + "".join(f"- [{who(o)} on {app_name(o)}: {what_full(o)}]({base}{offer_path(o.id)}): every term, the exact quotes, change history\n"
                  for o in sorted(offers, key=lambda x: x.id))
        + f"- [Changes]({base}/changes/): new, changed and ended offers, dated\n"
        + (f"- [Spotted, not yet verified]({base}/spotted/): offers seen on the web whose terms we haven't checked yet; "
           f"each links to its source. Not checked facts.\n" if spots else "") + "\n"
        + f"## For AI assistants and agents\n\n"
        f"- MCP server, hosted (read-only, Streamable HTTP, no sign-in): {MCP_URL}\n"
        f"- MCP server to run yourself (read-only, stdio, Python standard library): [fdfs_mcp.py]({base}{MCP_PATH}). Tools: find_offers "
        f"(by day, app, bank or text), match_cards (which of the user's cards gets a deal), get_offer, list_banks. "
        f"Setup: [For agents]({base}/agents/)\n"
        f"- Every offer in plain text, with its rules, dates, source and quotes: [llms-full.txt]({base}/llms-full.txt)\n"
        f"- To answer \"does <bank> have a BookMyShow or District offer?\", read that bank's page above, or filter "
        f"offers.json by `issuer` and `platform`. Quote the cap and the key condition (day, minimum tickets, spend gate), "
        f"and say the date we checked it.\n"
        f"- Only offers in offers.json are checked against the issuer's terms. Anything on /spotted/ is a lead we haven't "
        f"checked: don't present it as a confirmed offer.\n"
        f"- Credit \"FDFS (bookmyfdfs.in)\" and link the offer's page (each offer's `url`).\n\n"
        f"## Data feeds (CC BY 4.0)\n\n- [offers.json]({base}/offers.json): checked offers with sources, quotes and check times\n"
        f"- [llms-full.txt]({base}/llms-full.txt): the same offers as plain text\n"
        f"- [changes.json]({base}/changes.json): the change log\n- [changes.xml]({base}/changes.xml): the change log as Atom\n\n"
        f"## Licence and method\n\n- Licence: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Credit \"FDFS (bookmyfdfs.in)\" and link the page. Quoted terms remain their owners'; the licence covers FDFS's compilation and structure.\n"
        f"- [How we check]({base}/how-we-check/): what we read, what a person reads, what we never read\n"
        f"- [Disclosures]({base}/disclosures/)\n",
        encoding="utf-8")
    (out / "llms-full.txt").write_text(llms_full(base, offers, now), encoding="utf-8")
    # decision 170: the header search index and the MCP server agents download
    (out / "search.json").write_text(json.dumps(search_index(site, offers, pages), ensure_ascii=False, separators=(",", ":")) + "\n",
                                     encoding="utf-8")
    (out / MCP_PATH.strip("/")).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "gen/fdfs_mcp.py", out / MCP_PATH.strip("/"))
    key_file = root / "data/indexnow-key.txt"
    if key_file.exists():
        key = key_file.read_text().strip()
        (out / f"{key}.txt").write_text(key + "\n", encoding="utf-8")
    proof = mcp_registry_proof(root)   # MCP Registry domain proof for in.bookmyfdfs/* (public key only)
    if proof:
        (out / ".well-known").mkdir(exist_ok=True)
        (out / ".well-known/mcp-registry-auth").write_text(proof + "\n", encoding="utf-8")
    (out / "site.webmanifest").write_text(json.dumps({
        "name": "FDFS · Film · Deals · Friends · Seats", "short_name": "FDFS", "start_url": "/", "display": "browser",
        "background_color": "#F6F5EE", "theme_color": "#203229", "icons": [
            {"src": "/assets/brand/favicon.svg", "sizes": "any", "type": "image/svg+xml"},
            {"src": "/assets/brand/app-icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/assets/brand/app-icon-512.png", "sizes": "512x512", "type": "image/png"}]}, indent=1) + "\n", encoding="utf-8")
    # GitHub Pages custom domain + HTTPS depend on these two files surviving every deploy (publish branch: main).
    (out / "CNAME").write_text(urlparse(base).netloc, encoding="utf-8")   # exactly "bookmyfdfs.in", like the live file
    (out / ".nojekyll").write_text("", encoding="utf-8")
    a = out / "assets"
    (a / "fonts").mkdir(parents=True)
    for f in sorted((root / "assets/fonts").glob("*.woff2")):
        shutil.copyfile(f, a / "fonts" / f.name)
    (a / "site.css").write_text(site_css(root), encoding="utf-8")
    (a / "search.js").write_text(HS_JS + "\n", encoding="utf-8")   # decision 170: one cached file, not inline on every page
    (a / "brand").mkdir()
    for name in ("favicon.svg", "apple-touch-icon.png", "app-icon-192.png", "app-icon-512.png"):
        shutil.copyfile(root / "brand/logo" / name, a / "brand" / name)
    # decision 171: the v2 preview, after the live site is complete. Its pages are written here only: never in pages,
    # the state, the sitemap, llms.txt, search.json or .changed-urls.txt (so never sent to IndexNow).
    v2 = V2.build_v2(site, pages, offers, spots, now, out, urlparse(cfg["base_url"]).hostname.removeprefix("www.")) if offers else []
    (out / ".changed-urls.txt").write_text("".join(base + p + "\n" for p in sorted(changed)), encoding="utf-8")
    Path(state_path).write_text(json.dumps(new_state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"pages": [p.path for p in pages], "held": held, "warnings": warn, "changed": changed, "og": specs,
            "og_rendered": site.og_render, "spotted": [x.id for x in spots], "spotted_dropped": spot_drop, "v2": v2}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Build the FDFS static site into dist/ (never publishes).")
    ap.add_argument("--data", default=str(ROOT / "data/offers.json"))
    ap.add_argument("--history", default=str(ROOT / "data/history"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    # Local builds keep their own state; data/build-state.json is the PUBLISHED state, written only by deploy.sh.
    ap.add_argument("--state", default=str(ROOT / "data/.build-state.local.json"))
    ap.add_argument("--config", default=str(ROOT / "data/site.json"))
    ap.add_argument("--snapshot", action="store_true", help="save today's export into data/history if missing")
    ap.add_argument("--no-og", action="store_true", help="skip per-page OG PNGs (pages then use the dateless brand card)")
    ap.add_argument("--spotted", default=str(ROOT / "data/spotted.json"), help="leads seen on the web (decision 135)")
    a = ap.parse_args(argv)
    r = build(Path(a.data), Path(a.history), Path(a.out), Path(a.state), Path(a.config), ROOT, a.snapshot,
              render_og=not a.no_og, spotted=Path(a.spotted))
    print(f"built {len(r['pages'])} pages into {a.out} (per-page OG cards: {'yes' if r['og_rendered'] else 'no, brand card'})")
    for p in r["pages"]:
        print("  ", p)
    for w in r["warnings"]:
        print("  warning:", w)
    print(f"changed pages: {len(r['changed'])}")


if __name__ == "__main__":
    main()
