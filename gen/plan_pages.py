"""P3 (decisions 150-157): saved offers, the sort control, the deal calendar (/calendar/) and the "Before you pay"
checklist. Kept out of fdfs_site.py so parallel work there merges cleanly. fdfs_site binds itself as `g` at import.

Rules this module keeps (tests/test_plan_p3.py checks them):
- No price inputs, no computed rupee outcome, no "cheaper"/"better value" wording, no platform sort (owner, 26 Nov).
- The calendar's dates come from the export's generated_at (IST). The browser only re-labels "today" and past days.
- Booking-day offers and show-day offers are listed separately. A monthly reset is marked only on the 1st of a month,
  and only for an offer whose quoted terms say "calendar month". Anything else: no reset date.
- Each checklist item links to a real offer that has that condition, or says none has it.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

g = None   # fdfs_site, bound by fdfs_site at import (avoids a circular import)

PLAN_JS_SRC = (Path(__file__).resolve().parent / "plan.js").read_text(encoding="utf-8")


def _css(name: str) -> str:
    src = (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")
    return re.sub(r"\s*\n\s*", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S)).strip()


CAL_CSS = _css("plan-calendar.css")     # /calendar/ only
BP_CSS = _css("plan-checklist.css")     # offer pages and /calendar/ (the checklist)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SORTS = (("recent", "Most recently checked"), ("ends", "Ends soonest"), ("cap", "Highest stated cap"))


def plan_js() -> str:
    return g._min_js(PLAN_JS_SRC)


# ---------------------------------------------------------------- data for the browser
def label(o) -> str:
    return f"{g.who(o)} on {g.app_name(o)}"


def stated_cap(o) -> int | None:
    """The rupee cap the terms state (free ticket cap or benefit cap). A flat amount is a benefit, not a cap."""
    v = o.value
    n = v.get("free_cap") or v.get("cap")
    return int(n) if isinstance(n, (int, float)) and n > 0 else None


def plan_data(offers: list, gone: dict | None = None) -> str:
    """var FDFS_PLAN (offer IDs are already URL-safe slugs, so the browser builds /offer/<id>/ itself):
    o = live offers {id: [label, stated cap or null, end date or null]}; g = offers that had a page
    and are gone {id: label}, so a saved ID that is no longer listed still gets its name and history link."""
    o = {x.id: [label(x), stated_cap(x), x.valid_to.isoformat() if x.valid_to else None] for x in offers}
    gn = {}
    for oid, raw in sorted((gone or {}).items()):
        if oid not in o:
            gn[oid] = label(g.norm(raw))
    lit = json.dumps({"o": o, "g": gn}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    return f"var FDFS_PLAN={lit};"


def page_js(offers: list, gone: dict | None = None) -> str:
    return plan_data(offers, gone) + "\n" + plan_js()


def save_button(o, gone: bool = False) -> str:
    """The offer page's Save toggle. Hidden until plan.js runs (a control that can't work is never shown)."""
    return (f'<button type="button" class="sv sv-l" data-sv="{g.E(o.id)}"{" data-gone" if gone else ""} aria-pressed="false" '
            f'hidden>{HEART}<span class="sv-t">Save</span><span class="sr"> this offer</span></button>')   # name starts with the visible text


HEART = ('<svg class="ic sv-i" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13.6S1.8 9.9 1.8 5.7A3.1 3.1 0 0 1 8 4.4a3.1 3.1 0 0 1 '
         '6.2 1.3C14.2 9.9 8 13.6 8 13.6z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>')


# ---------------------------------------------------------------- "Before you pay" (5 checks)
def month_quote(o) -> str | None:
    """The quoted span that puts the limit on a CALENDAR month (not a spend rule). None if the terms don't say so."""
    for k in ("monthly_limit", "value", "cap_text", "quota_note", "days"):
        q = o.quotes.get(k)
        for s in (q if isinstance(q, list) else [q]):
            if isinstance(s, str) and re.search(r"calendar month", s, re.I) and not re.search(r"spend", s, re.I):
                return s
    return None


def _redeem(o) -> str | None:
    if o.code:
        return f"apply the code {o.code}"
    h = o.raw.get("how_to_redeem") or {}
    if isinstance(h, dict) and h.get("method") == "pick_offer" and h.get("label"):
        return f"pick “{h['label']}” in the offers list"
    return None


CHECKS = (
    ("day", "Booking day or show day?",
     "Some terms count the day you book, others the day of the show. Pick your date by the one that counts.",
     lambda o: o.day_basis in ("booking", "show")),
    ("month", "Monthly benefit left?",
     "A monthly limit counts every use on that card. If you've used it this month, the next booking won't get it.",
     lambda o: bool(o.monthly_limit)),
    ("pay", "Whole payment on the card",
     "Pay the full amount with the eligible card. A wallet or a split payment can lose the offer.",
     lambda o: "full_payment_on_card" in o.conditions or "no_wallet" in o.conditions),
    ("min", "Minimum tickets",
     "Some offers need 2 or more tickets in one booking.",
     lambda o: bool(o.min_tickets and o.min_tickets >= 2)),
    ("see", "See the discount before you pay",
     "Apply the code or pick the offer, then check the discount shows on the payment page before you pay.",
     lambda o: _redeem(o) is not None),
)


def _this(key: str, o) -> str:
    """What this offer's terms say for one check."""
    if key == "day":
        return g.basis_text(o)
    if key == "month":
        return g.times(o.monthly_limit) if o.monthly_limit else "No monthly limit stated in the terms"
    if key == "pay":
        bits = [g.CONDITIONS[c] for c in ("full_payment_on_card", "no_wallet") if c in o.conditions]
        return ". ".join(bits) if bits else "Not stated in the terms"
    if key == "min":
        return g.min_text(o)
    r = _redeem(o)
    return r[0].upper() + r[1:] if r else "The terms we hold don't say how to apply it"


def _example(key: str, o) -> str:
    if key == "day":
        t = g.basis_text(o).split(".")[0]
        return t[0].lower() + t[1:]
    if key == "month":
        return g.times(o.monthly_limit).lower()
    if key == "pay":
        return "full payment on the card" if "full_payment_on_card" in o.conditions else "not with wallet payments"
    if key == "min":
        return f"{o.min_tickets}+ tickets in one booking"
    return _redeem(o)


def checklist(offers: list, this=None, open_: bool = False, head: str = "Before you pay") -> str:
    """Plain HTML, no FAQ markup. Each check links to a real example offer with that condition (never this one)."""
    movie = sorted([o for o in offers if o.is_movie], key=g.home_order)
    li = ""
    for key, title, line, has in CHECKS:
        ex = next((o for o in movie if has(o) and (this is None or o.id != this.id)), None)
        bits = []
        if this is not None:
            bits.append(f'<span class="bp-this"><strong>This offer:</strong> {g.E(_this(key, this))}.</span>')
        if ex:
            bits.append(f'<span class="bp-ex">Example: <a href="{g.offer_path(ex.id)}">{g.E(label(ex))}</a> '
                        f'({g.E(_example(key, ex))})</span>')
        elif this is None or not has(this):
            bits.append('<span class="bp-ex">No offer we list has this condition right now.</span>')
        li += (f'<li data-bp="{key}"><span class="bp-n" aria-hidden="true"></span><div><p class="bp-h">{g.E(title)}</p>'
               f'<p>{g.E(line)}</p><p class="bp-x">{" ".join(bits)}</p></div></li>')
    return (f'<details class="bp"{" open" if open_ else ""}><summary><span class="bp-s">{g.E(head)}</span>'
            f'<span class="bp-c">{"" if open_ else "5 checks"}</span></summary><ol class="bp-l">{li}</ol>'
            f'<p class="bp-f">Your app shows the final price and whether the offer applied.</p></details>')


# ---------------------------------------------------------------- the deal calendar (/calendar/)
def _short(o) -> str:
    return f"{g.who(o)} · {g.app_name(o)}"


def _pill(o, tag: str = "", cls: str = "") -> str:
    t = f'<span class="cl-t">{g.E(tag)}</span>' if tag else ""
    return (f'<li class="cl-o{(" " + cls) if cls else ""}"><a href="{g.offer_path(o.id)}">{g.E(_short(o))}</a>'
            f'<span class="cl-v">{g.E(g.what(o))}, {g.E(g.cap(o))}</span>{t}</li>')


def _bank(o) -> str:
    return g.bank_label(g.bank_id(o.issuer), o.issuer) if o.is_bank else g.who(o)


def _list(items: list, limit: int, cls: str = "cl-ul") -> str:
    """Pills [(offer, tag, class)]. Past `limit`, grouped by bank into closed <details> (still crawlable links), so a busy
    day never stacks 20 cards. Groups keep the page order (home_order) inside, banks A to Z."""
    if len(items) <= limit:
        return f'<ul class="{cls}">' + "".join(_pill(*x) for x in items) + "</ul>"
    groups: dict = {}
    for x in items:
        groups.setdefault(_bank(x[0]), []).append(x)
    return '<div class="cl-gs">' + "".join(
        f'<details class="cl-g"><summary><span class="cl-gb">{g.E(b)}</span><span class="cl-gn">{len(xs)} offer{"s" if len(xs) != 1 else ""}'
        f'</span></summary><ul class="cl-ul">{"".join(_pill(*x) for x in xs)}</ul></details>'
        for b, xs in sorted(groups.items(), key=lambda kv: kv[0].lower())) + "</div>"


def _fold(lis: str, n: int, what: str) -> str:
    """A long list of quotes folds behind one summary."""
    ul = f'<ul class="cl-q">{lis}</ul>'
    return ul if n <= 6 else f'<details class="cl-g cl-fold"><summary><span class="cl-gb">Show the {n} {what}</span></summary>{ul}</details>'


def week(today: date, n: int = 7) -> list:
    return [today + timedelta(days=i) for i in range(n)]


SPARE_DAYS = 7   # decision 162: 7 more days, kept out of view, so the browser can start the 7 days on the visitor's today


def calendar_data(offers: list, today: date, n: int = 7) -> dict:
    """Per day: book (day-specific booking offers), show (show-day offers), ends, resets. Plus the every-day and
    no-days groups, said once. Pure: tests call it directly."""
    movie = sorted([o for o in offers if o.is_movie], key=g.home_order)
    every = [o for o in movie if "any" in o.days]
    nodays = [o for o in movie if "any" not in o.days and not g.day_keys(o)]
    resets = [(o, month_quote(o)) for o in movie if o.monthly_limit and month_quote(o)]
    rolling = [o for o in movie if o.monthly_limit and not month_quote(o)]
    days = []
    for d in week(today, n):
        k = DAYS[d.weekday()]
        named = [o for o in movie if "any" not in o.days and k in g.day_keys(o)]
        days.append({"date": d, "key": k,
                     "book": [o for o in named if o.day_basis != "show"],
                     "show": [o for o in named if o.day_basis == "show"],
                     "ends": [o for o in movie if o.valid_to == d],
                     "resets": [o for o, _ in resets] if d.day == 1 else []})
    return {"days": days, "every": every, "nodays": nodays, "resets": resets, "rolling": rolling, "movie": movie}


def _day_cell(x: dict, n_every: int, spare: bool = False) -> str:
    d, k = x["date"], x["key"]
    parts = ""
    if x["book"]:
        parts += '<p class="cl-h">Book this day</p>' + _list(
            [(o, ("show any day" if "any" in o.show_days else "") if o.day_basis == "booking" else
              "terms don't say booking or show day", "cl-key") for o in x["book"]], 4)
    if x["show"]:
        parts += '<p class="cl-h">Show on this day</p>' + _list([(o, "book any time before", "cl-show") for o in x["show"]], 4)
    marks = ""
    for o in x["ends"]:
        marks += f'<li class="cl-m cl-end">Ends: <a href="{g.offer_path(o.id)}">{g.E(_short(o))}</a></li>'
    if x["resets"]:
        n = len(x["resets"])
        marks += (f'<li class="cl-m cl-reset">New calendar month: <a href="#monthly">{n} monthly limit'
                  f'{"s restart" if n != 1 else " restarts"}</a></li>')
    if marks:
        parts += f'<ul class="cl-ms">{marks}</ul>'
    if n_every:
        parts += f'<p class="cl-e"><a href="#every-day">+ {n_every} every-day offer{"s" if n_every != 1 else ""}</a></p>'
    if not (x["book"] or x["show"]):
        parts = '<p class="cl-none">No offer tied to this day.</p>' + parts
    return (f'<li class="cl-d{" cl-x" if spare else ""}" data-date="{d.isoformat()}" data-k="{k}"><h3 class="cl-dh"><time datetime="{d.isoformat()}">'
            f'<span class="cl-wd">{g.DAY[k][:3]}</span> <span class="cl-dn">{d.day}</span> <span class="cl-mo">{d:%b}</span></time>'
            f'<span class="cl-today" hidden></span></h3>{parts}</li>')


def calendar_page(site, offers: list, today: date):
    c = calendar_data(offers, today, 7 + SPARE_DAYS)
    movie, all_days = c["movie"], c["days"]
    days = all_days[:7]
    first, last = days[0]["date"], days[-1]["date"]
    rng = f"{g.fmt_dm(first)} to {g.fmt_dm(last)}"
    tied = sorted({o.id: o for x in days for o in x["book"] + x["show"]}.values(), key=g.home_order)
    reset_day = next((x["date"] for x in days if x["resets"]), None)
    ends = [o for x in days for o in x["ends"]]
    bits = []
    for o in tied:
        ks = sorted(g.day_keys(o), key=g.DAY_IDX.get)
        dd = [x["date"] for x in days if x["key"] in ks]
        when = " and ".join(f"{g.DAY[DAYS[d.weekday()]]}, {g.fmt_dm(d)}" for d in dd)
        verb = "book on" if o.day_basis == "booking" else "for shows on" if o.day_basis == "show" else "on"
        bits.append(f"{g.who(o)} ({verb} {when})")
    if movie:
        answer = (f"<strong>{g.E(rng)}:</strong> "
                  + ((f"{len(tied)} offer{'s' if len(tied) != 1 else ''} depend{'s' if len(tied) == 1 else ''} on the day: "
                      f"{g.E(g.join_and(bits))}. " if len(tied) <= 3 else
                      f"{len(tied)} offers depend on the day: see each day below. ") if tied else "No offer is tied to a day this week. ")
                  + f"{len(c['every'])} work{'s' if len(c['every']) == 1 else ''} every day"
                  + (f"; {len(c['nodays'])} don't name days" if c["nodays"] else "") + ". "
                  + (f"A new calendar month starts {g.fmt_dm(reset_day)}: the monthly limit restarts for "
                     f"{len(c['resets'])} offer{'s' if len(c['resets']) != 1 else ''}. " if reset_day else "")
                  + (f"{len(ends)} end{'s' if len(ends) == 1 else ''} in these 7 days." if ends else "No offer ends in these 7 days."))
    else:
        answer = f"<strong>{g.E(rng)}:</strong> no movie offer passes our checks right now."
    grid = "".join(_day_cell(x, len(c["every"]), i >= 7) for i, x in enumerate(all_days))
    every = _list([(o, "", "") for o in c["every"]], 6, "cl-ul cl-list") if c["every"] else ""
    nod = _list([(o, "", "") for o in c["nodays"]], 6, "cl-ul cl-list") if c["nodays"] else ""
    mq = "".join(f'<li><a href="{g.offer_path(o.id)}">{g.E(_short(o))}</a>: {g.E(g.times(o.monthly_limit).lower())}. '
                 f'<q>{g.E(q)}</q></li>' for o, q in c["resets"])
    roll = "".join(f'<li><a href="{g.offer_path(o.id)}">{g.E(_short(o))}</a>: {g.E(g.times(o.monthly_limit).lower())}.</li>'
                   for o in c["rolling"])
    body = (f'<section class="wrap block" aria-labelledby="h-cal"><div class="sec-head"><h2 id="h-cal">The next 7 days</h2>'
            f'<p class="meta">Dates in IST, from our check on {g.E(g.fmt_day(site.now.astimezone(g.IST).date()))}</p></div>'
            f'<p class="cl-key-l"><span class="cl-sw cl-sw-b" aria-hidden="true"></span>Book this day: the day you book counts. '
            f'<span class="cl-sw cl-sw-s" aria-hidden="true"></span>Show on this day: the day of the show counts.</p>'
            f'<ol class="cal" aria-label="Offers by day, {g.E(rng)}">{grid}</ol>'
            f'<p class="cl-stale" data-cl-stale hidden>These 7 days have passed. The plan updates after our next check. '
            f'<a href="/">See the current offers</a>.</p></section>'
            + (f'<section class="wrap block" id="every-day" aria-labelledby="h-ev"><div class="sec-head"><h2 id="h-ev">Every day</h2></div>'
               f'<p class="cl-p">Their terms say any day of the week, so the date doesn\'t matter.</p>{every}</section>'
               if every else "")
            + (f'<section class="wrap block" aria-labelledby="h-nd"><div class="sec-head"><h2 id="h-nd">Days not stated</h2></div>'
               f'<p class="cl-p">The terms we read don\'t name days. Check the terms before you pick a date.</p>'
               f'{nod}</section>' if nod else "")
            + f'<section class="wrap block" id="monthly" aria-labelledby="h-mo"><div class="sec-head"><h2 id="h-mo">Monthly limits</h2></div>'
            + (f'<p class="cl-p">These terms put the limit on a calendar month, so it restarts on the 1st:</p>{_fold(mq, len(c["resets"]), "quotes")}'
               if mq else '<p class="cl-p">No offer we list puts its limit on a calendar month.</p>')
            + (f'<p class="cl-p">These have a monthly limit, but the terms don\'t say when the month starts, so we show no reset date:</p>'
               f'{_fold(roll, len(c["rolling"]), "offers")}' if roll else "")
            + '</section>'
            f'<section class="wrap block" aria-labelledby="h-ck"><div class="sec-head"><h2 id="h-ck">Before you pay</h2></div>'
            f'{checklist(offers, open_=True, head="Five checks for this weekend")}</section>'
            f'<section class="wrap block"><ul class="links"><li><a href="/">Every offer that passes our checks</a></li>'
            f'<li><a href="/how-we-check/">How we check</a></li></ul></section>')
    key = g.facts(movie) + first.isoformat()
    stamp = g.stamp_of(movie) if movie else site.now
    desc = (f"Movie ticket offers for {rng}, day by day: which to book on which day, booking day vs show day, "
            f"and when monthly limits restart. From the official terms.")
    return g.Page("/calendar/", "Movie ticket offers this week: plan by day · FDFS", desc,
                  "Movie ticket offers this week, <em>day by day.</em>", answer, body,
                  [("Offers", "/"), ("Calendar", "/calendar/")], "Checked" if movie else "Updated", stamp, key,
                  css=CAL_CSS + BP_CSS, js=plan_js())
