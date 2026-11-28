#!/usr/bin/env python3
"""FDFS MCP server: lets an AI agent answer "which of my cards gets me a deal on this booking?" from FDFS's
checked offers (decision 170; match_cards and plan text added 27 Nov).

- Read-only. It reads the public feed https://bookmyfdfs.in/offers.json (CC BY 4.0) and nothing else.
- Standard library only, Python 3.9+. Speaks MCP over stdio (newline-delimited JSON-RPC 2.0).
- Only offers checked against the issuer's official terms are in that feed. Spotted leads are never included.
- Offers past their end date are left out; offers not re-checked for 7 days are marked so.

Run it from an MCP client, for example:
    {"mcpServers": {"fdfs": {"command": "python3", "args": ["/path/to/fdfs_mcp.py"]}}}
Options: --feed <url or file> (default: the live feed; env FDFS_FEED also works).
Credit "FDFS (bookmyfdfs.in)" and link each offer's `url` when you quote it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

VERSION = "1.1.0"
FEED = "https://bookmyfdfs.in/offers.json"
IST = timezone(timedelta(hours=5, minutes=30))
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
CACHE_SECONDS = 600
STALE_DAYS = 7
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri",
             "saturday": "sat", "sunday": "sun", **{d: d for d in DAYS}}
APPS = {"bms": "BookMyShow", "district": "District", "pvr": "PVR INOX", "inox": "PVR INOX"}
APP_WORDS = {"bookmyshow": "bms", "bms": "bms", "book my show": "bms", "district": "district", "zomato district": "district",
             "pvr": "pvr", "inox": "pvr", "pvr inox": "pvr"}
NOTE = ("Checked offers from FDFS (bookmyfdfs.in): each was read from the issuer's official terms at `checked_at` (IST). "
        "Quotas and spend rules can't be checked from outside, so tell the user to read the terms before paying. "
        "Credit \"FDFS (bookmyfdfs.in)\" and link the offer's `url`.")

TOOLS = [
    {"name": "find_offers",
     "title": "Find checked movie ticket offers",
     "description": ("Checked bank, card and membership offers on movie tickets in India (BookMyShow, District and others), "
                     "from FDFS. Filter by booking day, app, bank or free text. Answers questions like \"which card gets me a "
                     "deal on Saturday on BookMyShow?\". Every result has its cap, key conditions, end date, official source "
                     "and check time."),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "day": {"type": "string", "description": "Booking or show day: monday..sunday, mon..sun, today or tomorrow (IST)."},
         "app": {"type": "string", "description": "BookMyShow, District or PVR INOX."},
         "bank": {"type": "string", "description": "Issuer name, for example HSBC, Axis, IndusInd."},
         "query": {"type": "string", "description": "Free text matched against the card, issuer, benefit and conditions."},
         "include_events": {"type": "boolean", "description": "Also return live-event (not movie) offers. Default false."}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": True}},
    {"name": "match_cards",
     "title": "Which of my cards gets a movie ticket deal?",
     "description": ("Give the cards in the user's wallet (for example \"Axis My Zone\", \"HDFC Diners Club Privilege\", "
                     "\"ICICI\") and, if known, the app, day and number of tickets. Returns, for each card, the checked "
                     "offers it qualifies for, best first, and says whether the terms name that card or only its bank. "
                     "Each match has a ready message to send a WhatsApp group and a link to the offer page."),
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["cards"], "properties": {
         "cards": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "string", "maxLength": 80},
                   "description": "Card names as the user says them: bank plus card, or just the bank."},
         "app": {"type": "string", "description": "BookMyShow, District or PVR INOX."},
         "day": {"type": "string", "description": "Booking or show day: monday..sunday, mon..sun, today or tomorrow (IST)."},
         "tickets": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many tickets in the booking."},
         "include_events": {"type": "boolean", "description": "Also match live-event (not movie) offers. Default false."}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": True}},
    {"name": "get_offer",
     "title": "Get one offer's full terms",
     "description": "Every recorded term of one checked offer by its id (from find_offers): quotes, limits, dates, sources.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["id"],
                     "properties": {"id": {"type": "string", "description": "The offer id, for example hsbc-premier-bms-bogo."}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": True}},
    {"name": "list_banks",
     "title": "List banks with checked offers",
     "description": "Each issuer with checked movie ticket offers right now, how many, and on which apps.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": True}},
]


class ToolError(Exception):
    pass


class Feed:
    def __init__(self, src: str):
        self.src, self.data, self.at = src, None, 0.0

    def get(self) -> dict:
        if self.data is None or time.monotonic() - self.at > CACHE_SECONDS:
            try:
                if self.src.startswith(("https://", "http://")):
                    req = urllib.request.Request(self.src, headers={"User-Agent": f"fdfs-mcp/{VERSION}",
                                                                    "Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        raw = r.read(5_000_000)
                else:
                    with open(self.src, "rb") as f:
                        raw = f.read(5_000_000)
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("offers"), list):
                    raise ValueError("no offers list")
            except Exception as e:  # keep the last good copy if one exists
                if self.data is not None:
                    return self.data
                raise ToolError(f"Couldn't read the FDFS feed ({type(e).__name__}). Try again shortly.") from None
            self.data, self.at = data, time.monotonic()
        return self.data


def now_ist() -> datetime:
    v = os.environ.get("FDFS_NOW")          # tests only: ISO time
    return (datetime.fromisoformat(v) if v else datetime.now(timezone.utc)).astimezone(IST)


def _date(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _dt(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=IST)
    except (TypeError, ValueError):
        return None


def app_of(o: dict) -> str:
    p = str(o.get("platform") or "").lower()
    return "pvr" if p in ("pvr", "inox", "pvr_inox", "pvrinox") else p


def live(o: dict, now: datetime) -> tuple[bool, str]:
    """(still valid today?, freshness note)."""
    end = _date(o.get("valid_to"))
    if end and end < now.date():
        return False, ""
    start = _date(o.get("valid_from"))
    if start and start > now.date():
        return True, f"Starts on {start.isoformat()}: not usable before then."
    ck = _dt(o.get("checked_at"))
    if ck and now - ck > timedelta(days=STALE_DAYS):
        return True, "Not re-checked in the last 7 days: confirm on the official terms."
    return True, ""


def day_key(v: str, now: datetime) -> str:
    s = v.strip().lower()
    if s == "today":
        return DAYS[now.weekday()]
    if s == "tomorrow":
        return DAYS[(now.weekday() + 1) % 7]
    if s in DAY_WORDS:
        return DAY_WORDS[s]
    raise ToolError("day must be monday..sunday, today or tomorrow")


DAY_NAMES = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def _when(o: dict) -> str:
    days = [str(d).lower() for d in (o.get("days") or [])]
    if not days:
        return ""
    if "any" in days:
        return "any day"
    return "/".join(DAY_NAMES.get(d, d) for d in days)


def deal_text(o: dict) -> str:
    """The benefit in a few words, from the checked value and cap."""
    v, cap = o.get("value") or {}, str(o.get("cap_text") or "")
    cap = "" if "see terms" in cap.lower() else cap
    if o.get("kind") == "bogo":
        return f"2nd ticket free {cap}".strip()
    if v.get("pct"):
        return f"{v['pct']}% off" + (f", {cap}" if cap else "")
    if v.get("flat"):
        return f"\u20b9{v['flat']} off"
    if o.get("kind") == "complimentary" and v.get("free_tickets") and v.get("period") in ("month", "quarter", "year"):
        n = int(v["free_tickets"])
        return f"{n} free ticket{'' if n == 1 else 's'} a {v['period']}" + (f", {cap}" if cap else "")
    return cap or "see the terms"


def plan_text(o: dict) -> str:
    """A message to send friends, built only from checked fields, with the offer page link."""
    where = APPS.get(app_of(o), o.get("platform")) + (" live events" if o.get("category") == "events" else "")
    bits = [f"{o.get('label') or o.get('issuer')} on {where}"]
    bits.append(deal_text(o))
    w = _when(o)
    if w:
        bits.append(w)
    if o.get("min_tickets"):
        bits.append(f"min {o['min_tickets']} tickets")
    end = _date(o.get("valid_to"))
    tail = f" Valid until {end.day} {end.strftime('%b')}." if end else ""
    ck = _dt(o.get("checked_at"))
    tail += f" Terms checked {ck.astimezone(IST).day} {ck.astimezone(IST).strftime('%b')} by FDFS:" if ck else " Checked by FDFS:"
    return ", ".join(bits) + "." + tail + f" {o.get('url')}"


def _value(o: dict) -> float:
    v = o.get("value") or {}
    return float(max([v.get(k) or 0 for k in ("free_cap", "cap", "flat")] or [0]))


_STOP = {"card", "cards", "credit", "debit", "bank", "club", "the", "my", "and", "of"}


def _toks(s: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _STOP]


def _issuer_key(issuer: str) -> list:
    return _toks(issuer.replace("FIRST", "")) or _toks(issuer)


NETWORKS = {"visa": "visa", "mastercard": "mastercard", "rupay": "rupay", "amex": "amex", "diners": "diners"}


def card_match(o: dict, card: str) -> str:
    """'named card', 'all cards', 'select cards', 'bank only' or '' for one offer and one card as the user named it.
    Follows docs/growth/offer-schema.md: `unstated` scope never becomes "your card works"; a debit offer never
    matches a card the user called credit (and the other way round); a stated network must agree."""
    low = card.lower()
    toks, joined = set(_toks(card)), "".join(_toks(card))
    inst = str(o.get("instrument") or "").lower()
    if inst in ("credit", "debit") and ({"credit", "debit"} - {inst}) & set(re.findall(r"[a-z]+", low)):
        return ""
    net = str(o.get("network") or "").lower()
    said = {n for w, n in NETWORKS.items() if w in low}
    if net and said and net not in said:
        return ""
    key = _issuer_key(str(o.get("issuer") or ""))
    if key and key[0] in NETWORKS.values() and key[0] in said:     # a network-wide offer (issuer: Visa)
        key = []
        toks -= said
    elif not key or not all(k in toks for k in key):
        return ""
    variants = o.get("card_variants") or []
    for v in variants:
        vt = [t for t in _toks(v) if t not in key]
        if vt and (all(t in toks for t in vt) or (len("".join(vt)) >= 4 and "".join(vt) in joined)):
            return "named card"
    named = toks - set(key) - set(NETWORKS)
    if o.get("variants_scope") == "unstated":
        return "select cards"                # "select HSBC cards": never promise it, say check at payment
    if o.get("variants_scope") == "all":
        return "all cards"
    # The terms list other cards of this bank (or don't say which): only a bare bank name gets a hedged match.
    return "" if named else "bank only"


RANK = {"named card": 0, "all cards": 1, "select cards": 2, "bank only": 3}
HINTS = {"select cards": "The terms say only select cards of this bank qualify, without listing them. Tell the user to "
                         "check on the payment screen; don't promise it.",
         "bank only": "The terms name specific cards of this bank. Check the user's card is in `cards` before "
                      "promising the offer."}


def match_cards(feed: dict, args: dict, now: datetime) -> dict:
    cards = args.get("cards")
    if not isinstance(cards, list) or not cards or not all(isinstance(c, str) and c.strip() for c in cards):
        raise ToolError("cards must be a list of card names, for example [\"Axis My Zone\", \"ICICI\"]")
    base = {k: args[k] for k in ("app", "day", "include_events") if k in args}
    pool = find_offers(feed, base, now)["offers"]
    by_id = {o.get("id"): o for o in feed.get("offers", [])}
    tickets = args.get("tickets")
    rows = []
    for card in cards[:10]:
        hits = []
        for s in pool:
            o = by_id.get(s["id"]) or {}
            how = card_match(o, card)
            if not how:
                continue
            if isinstance(tickets, int) and isinstance(o.get("min_tickets"), int) and tickets < o["min_tickets"]:
                continue
            hits.append({**s, "card_match": how})
        rank = RANK
        hits.sort(key=lambda h: (rank[h["card_match"]], -_value(by_id.get(h["id"]) or {}), h.get("days_left") or 0))
        row = {"card": card, "count": len(hits), "offers": hits}
        if not hits:
            row["hint"] = "No checked offer for this card with these filters."
        elif hits[0]["card_match"] in HINTS:
            row["hint"] = HINTS[hits[0]["card_match"]]
        rows.append(row)
    out = {"cards": rows, "generated_at": feed.get("generated_at"), "note": NOTE}
    if any(r["offers"] for r in rows):
        out["best"] = min((r["offers"][0] for r in rows if r["offers"]),
                          key=lambda h: (RANK[h["card_match"]],
                                         -_value(by_id.get(h["id"]) or {})))["id"]
    return out


def summary(o: dict, now: datetime, note: str) -> dict:
    end = _date(o.get("valid_to"))
    out = {"id": o.get("id"), "offer": o.get("label") or o.get("issuer"), "issuer": o.get("issuer"),
           "app": APPS.get(app_of(o), o.get("platform")), "deal": deal_text(o), "benefit": o.get("value"), "cap": o.get("cap_text"),
           "days": o.get("days") or "not stated in the terms", "day_basis": o.get("day_basis"), "min_tickets": o.get("min_tickets"),
           "monthly_limit": o.get("monthly_limit"), "conditions": o.get("quota_note"),
           "requires_purchase": o.get("requires_purchase"), "code": o.get("code"), "valid_to": o.get("valid_to"),
           "days_left": (end - now.date()).days if end else None,
           "ends": None if end else (o.get("validity_note") or "no end date in the terms"), "checked_at": o.get("checked_at"),
           "cards": o.get("card_variants"), "excludes": o.get("excludes"),
           "source_url": o.get("source_url"), "url": o.get("url")}
    out["plan_text"] = plan_text(o)
    out["whatsapp_url"] = "https://wa.me/?text=" + urllib.parse.quote(out["plan_text"])
    if note:
        out["freshness"] = note
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def find_offers(feed: dict, args: dict, now: datetime) -> dict:
    day = day_key(args["day"], now) if args.get("day") else None
    app = None
    if args.get("app"):
        app = APP_WORDS.get(str(args["app"]).strip().lower())
        if not app:
            raise ToolError("app must be BookMyShow, District or PVR INOX")
    bank = str(args.get("bank") or "").strip().lower()
    words = [w for w in str(args.get("query") or "").lower().split() if w]
    events = bool(args.get("include_events"))
    hits = []
    for o in feed.get("offers", []):
        ok, note = live(o, now)
        if not ok or (o.get("category") == "events" and not events):
            continue
        if app and app_of(o) != app:
            continue
        if bank and bank not in str(o.get("issuer") or "").lower() and bank not in str(o.get("label") or "").lower():
            continue
        days = [str(d).lower() for d in (o.get("days") or [])]
        if day and days and "any" not in days and day not in days:
            continue
        val = o.get("value") if isinstance(o.get("value"), dict) else {}
        hay = " ".join([*(str(o.get(k) or "") for k in ("label", "issuer", "cap_text", "quota_note", "kind", "platform")),
                        *(f"{k} {v}" for k, v in val.items()), *map(str, o.get("card_variants") or [])]).lower()
        if o.get("kind") == "bogo":
            hay += " bogo buy 1 get 1 buy one get one 2nd ticket free"
        if any(w not in hay.lower() for w in words):
            continue
        hits.append(summary(o, now, note))
    hits.sort(key=lambda x: (x.get("days_left") is None, x.get("days_left") or 0, str(x.get("id"))))
    out = {"count": len(hits), "offers": hits, "generated_at": feed.get("generated_at"), "note": NOTE}
    if day:
        out["day"] = {"key": day, "rule": "An offer matches when its terms name that day or every day. Offers whose terms "
                                          "name no day are included with days \"not stated in the terms\": say so, "
                                          "don't promise that day. `day_basis` says whether the day is the booking "
                                          "day or the show day."}
    if not hits:
        out["hint"] = ("No checked offer matches. FDFS lists only offers it has checked; there may be others it hasn't "
                       "verified. See https://bookmyfdfs.in/ for everything that passes its checks.")
    return out


def get_offer(feed: dict, args: dict, now: datetime) -> dict:
    oid = str(args.get("id") or "").strip()
    for o in feed.get("offers", []):
        if o.get("id") == oid:
            ok, note = live(o, now)
            rec = dict(o)
            rec["status"] = "current" if ok else "ended"
            if note:
                rec["freshness"] = note
            rec["plan_text"] = plan_text(o)
            rec["note"] = NOTE
            return rec
    raise ToolError(f"No checked offer with id {oid!r}. Use find_offers to list ids.")


def list_banks(feed: dict, args: dict, now: datetime) -> dict:
    banks: dict = {}
    for o in feed.get("offers", []):
        if not live(o, now)[0]:
            continue
        b = banks.setdefault(o.get("issuer") or "Other", {"issuer": o.get("issuer") or "Other", "offers": 0, "apps": set()})
        b["offers"] += 1
        b["apps"].add(APPS.get(app_of(o), str(o.get("platform"))))
    rows = [{**b, "apps": sorted(b["apps"])} for b in sorted(banks.values(), key=lambda x: (-x["offers"], x["issuer"]))]
    return {"count": len(rows), "banks": rows, "generated_at": feed.get("generated_at"), "note": NOTE}


HANDLERS = {"find_offers": find_offers, "match_cards": match_cards, "get_offer": get_offer, "list_banks": list_banks}


def readable(name: str, data: dict) -> str:
    """A short text answer that leads with each offer and its FDFS page, for clients that only show text."""
    def line(h):
        bits = [f"{h.get('offer')} on {h.get('app')}: {h.get('deal')}"]
        if isinstance(h.get("days"), list):
            bits.append(", ".join(h["days"]) if "any" not in h["days"] else "any day")
        if h.get("card_match"):
            bits.append(h["card_match"])
        if h.get("valid_to"):
            bits.append(f"until {h['valid_to']}")
        if h.get("freshness"):
            bits.append(h["freshness"].split(":")[0].lower())
        return "- " + ", ".join(bits) + f". {h.get('url')}"
    if name == "find_offers":
        lines = [line(h) for h in data["offers"][:15]] or [data.get("hint", "")]
        head = f"{data['count']} checked offers from FDFS (bookmyfdfs.in):"
    elif name == "match_cards":
        lines = []
        for r in data["cards"]:
            n = r["count"]
            lines.append(f"{r['card']}: " + (f"{n} offer{'s' if n != 1 else ''}" if n else r.get("hint", "none")))
            lines += [line(h) for h in r["offers"][:5]]
        head = "Card matches from FDFS (bookmyfdfs.in):"
    else:
        return ""
    return head + "\n" + "\n".join(lines) + "\nRead the terms before paying. Full data follows as JSON."


def handle(msg: dict, feed: Feed):
    """One JSON-RPC message in, one response (or None for a notification) out."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:                     # notifications (initialized, cancelled): nothing to answer
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "fdfs", "title": "FDFS movie ticket offers", "version": VERSION},
                   "instructions": NOTE + " Spotted (unverified) leads are never returned."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in HANDLERS:
            return err(-32602, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return err(-32602, "arguments must be an object")
        try:
            data = HANDLERS[name](feed.get(), args, now_ist())
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        content = [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}]
        lead = readable(name, data)
        if lead:
            content.insert(0, {"type": "text", "text": lead})
        return ok({"content": content, "structuredContent": data})
    return err(-32601, f"Method not found: {method}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    src = os.environ.get("FDFS_FEED") or FEED
    if "--feed" in argv:
        i = argv.index("--feed")
        src = argv[i + 1]
    if "--version" in argv:
        print(VERSION)
        return 0
    feed = Feed(src)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle(msg, feed) if isinstance(msg, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
