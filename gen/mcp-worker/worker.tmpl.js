// FDFS MCP server as a Cloudflare Worker: the same read-only tools as gen/fdfs_mcp.py, over MCP's Streamable HTTP
// transport (JSON-RPC 2.0 in a POST to /mcp, JSON answers). It reads https://bookmyfdfs.in/offers.json and keeps a
// copy for 10 minutes, so it follows the 00:05 IST publish with no deploy. No auth, no cookies, nothing about the
// user is stored or logged. Spotted (unverified) leads are never returned.
//
// Kept in step with gen/fdfs_mcp.py by tests/test_mcp_worker.py, which runs both on the same calls and requires
// identical answers. Change the two together.

// BEGIN CONSTANTS (copied from gen/fdfs_mcp.py; the parity test checks them)
const CONSTANTS = __CONSTANTS__;
// END CONSTANTS

const { VERSION, FEED, PROTOCOLS, CACHE_SECONDS, STALE_DAYS, DAYS, DAY_WORDS, APPS, APP_WORDS, NOTE, TOOLS, NETWORKS,
  RANK, HINTS, STOP, DAY_NAMES } = CONSTANTS;
const IST_MS = 330 * 60 * 1000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MAX_BODY = 64 * 1024;

class ToolError extends Error {}

// ---- feed --------------------------------------------------------------------------------------------------------
let cache = { data: null, at: 0 };

async function getFeed(env) {
  const src = (env && env.FDFS_FEED) || FEED;
  if (cache.data && Date.now() - cache.at <= CACHE_SECONDS * 1000) return cache.data;
  try {
    const r = await fetch(src, { headers: { "User-Agent": `fdfs-mcp-worker/${VERSION}`, Accept: "application/json" },
                                 cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (!data || typeof data !== "object" || !Array.isArray(data.offers)) throw new Error("no offers list");
    cache = { data, at: Date.now() };
    return data;
  } catch (e) {
    if (cache.data) return cache.data;                // keep the last good copy
    throw new ToolError(`Couldn't read the FDFS feed (${e.name || "Error"}). Try again shortly.`);
  }
}

// ---- dates (all in IST) ------------------------------------------------------------------------------------------
// A "day" is a UTC-midnight timestamp standing for that calendar date in IST, so differences are whole days.
function nowMs(env) {
  const v = env && env.FDFS_NOW;                       // tests only
  return v ? Date.parse(v) : Date.now();
}
const istDay = (ms) => { const d = new Date(ms + IST_MS); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); };
function dateOf(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v ?? ""));
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const d = new Date(t);
  return d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? t : null;
}
function dtOf(v) {
  if (v == null) return null;
  let s = String(v).replace("Z", "+00:00");
  if (!/^\d{4}-\d{2}-\d{2}/.test(s)) return null;
  if (!/[+-]\d{2}:?\d{2}$/.test(s) && s.length > 10) s += "+05:30";       // a time with no zone is IST
  if (s.length === 10) s += "T00:00:00+05:30";
  s = s.replace(/(\.\d{3})\d+/, "$1");
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}
const isoDate = (day) => new Date(day).toISOString().slice(0, 10);
const weekday = (ms) => (new Date(istDay(ms)).getUTCDay() + 6) % 7;    // Monday = 0, as in Python

// ---- helpers ported from gen/fdfs_mcp.py -------------------------------------------------------------------------
const str = (v) => (v == null || v === false || v === 0 || v === "" ? "" : String(v));    // Python str(v or "")
const falsy = (v) => v == null || v === false || v === 0 || v === "" || (Array.isArray(v) && !v.length) ||
  (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
const pyRepr = (s) => (s.includes("'") && !s.includes('"') ? `"${s}"` : `'${s.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);
function quote(s) {                                    // Python urllib.parse.quote(s), safe="/"
  return encodeURIComponent(s).replace(/%2F/g, "/").replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

function appOf(o) {
  const p = str(o.platform).toLowerCase();
  return ["pvr", "inox", "pvr_inox", "pvrinox"].includes(p) ? "pvr" : p;
}
const appName = (o) => (appOf(o) in APPS ? APPS[appOf(o)] : o.platform);

function live(o, now) {
  const today = istDay(now);
  const end = dateOf(o.valid_to);
  if (end !== null && end < today) return [false, ""];
  const start = dateOf(o.valid_from);
  if (start !== null && start > today) return [true, `Starts on ${isoDate(start)}: not usable before then.`];
  const ck = dtOf(o.checked_at);
  if (ck !== null && now - ck > STALE_DAYS * 86400000) return [true, "Not re-checked in the last 7 days: confirm on the official terms."];
  return [true, ""];
}

function dayKey(v, now) {
  const s = String(v).trim().toLowerCase();
  if (s === "today") return DAYS[weekday(now)];
  if (s === "tomorrow") return DAYS[(weekday(now) + 1) % 7];
  if (Object.prototype.hasOwnProperty.call(DAY_WORDS, s)) return DAY_WORDS[s];
  throw new ToolError("day must be monday..sunday, today or tomorrow");
}

function when(o) {
  const days = (falsy(o.days) ? [] : o.days).map((d) => String(d).toLowerCase());
  if (!days.length) return "";
  if (days.includes("any")) return "any day";
  return days.map((d) => DAY_NAMES[d] ?? d).join("/");
}

function dealText(o) {
  const v = isObj(o.value) ? o.value : {};
  let cap = str(o.cap_text);
  if (cap.toLowerCase().includes("see terms")) cap = "";
  if (o.kind === "bogo") return `2nd ticket free ${cap}`.trim();
  if (!falsy(v.pct)) return `${v.pct}% off` + (cap ? `, ${cap}` : "");
  if (!falsy(v.flat)) return `₹${v.flat} off`;
  if (o.kind === "complimentary" && !falsy(v.free_tickets) && ["month", "quarter", "year"].includes(v.period)) {
    const n = Number(v.free_tickets);
    return `${n} free ticket${n === 1 ? "" : "s"} a ${v.period}` + (cap ? `, ${cap}` : "");
  }
  return cap || "see the terms";
}

function planText(o) {
  const where = appName(o) + (o.category === "events" ? " live events" : "");
  const bits = [`${str(o.label) || o.issuer} on ${where}`, dealText(o)];
  const w = when(o);
  if (w) bits.push(w);
  if (!falsy(o.min_tickets)) bits.push(`min ${o.min_tickets} tickets`);
  const end = dateOf(o.valid_to);
  let tail = end !== null ? ` Valid until ${new Date(end).getUTCDate()} ${MONTHS[new Date(end).getUTCMonth()]}.` : "";
  const ck = dtOf(o.checked_at);
  if (ck !== null) {
    const d = new Date(ck + IST_MS);
    tail += ` Terms checked ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} by FDFS:`;
  } else tail += " Checked by FDFS:";
  return bits.join(", ") + "." + tail + ` ${o.url}`;
}

function value(o) {
  const v = isObj(o.value) ? o.value : {};
  return Math.max(...["free_cap", "cap", "flat"].map((k) => (falsy(v[k]) ? 0 : Number(v[k]))));
}

const toks = (s) => (String(s).toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => !STOP.includes(t));
const issuerKey = (issuer) => { const a = toks(issuer.replace(/FIRST/g, "")); return a.length ? a : toks(issuer); };

function cardMatch(o, card) {
  const low = card.toLowerCase();
  let tk = new Set(toks(card));
  const joined = toks(card).join("");
  const inst = str(o.instrument).toLowerCase();
  if ((inst === "credit" || inst === "debit") && (low.match(/[a-z]+/g) || []).includes(inst === "credit" ? "debit" : "credit")) return "";
  const net = str(o.network).toLowerCase();
  const said = new Set(Object.entries(NETWORKS).filter(([w]) => low.includes(w)).map(([, n]) => n));
  if (net && said.size && !said.has(net)) return "";
  let key = issuerKey(str(o.issuer));
  if (key.length && Object.values(NETWORKS).includes(key[0]) && said.has(key[0])) {
    key = [];
    tk = new Set([...tk].filter((t) => !said.has(t)));
  } else if (!key.length || !key.every((k) => tk.has(k))) return "";
  for (const v of falsy(o.card_variants) ? [] : o.card_variants) {
    const vt = toks(v).filter((t) => !key.includes(t));
    if (vt.length && (vt.every((t) => tk.has(t)) || (vt.join("").length >= 4 && joined.includes(vt.join(""))))) return "named card";
  }
  const named = [...tk].filter((t) => !key.includes(t) && !(t in NETWORKS));
  if (o.variants_scope === "unstated") return "select cards";
  if (o.variants_scope === "all") return "all cards";
  return named.length ? "" : "bank only";
}

function summary(o, now, note) {
  const end = dateOf(o.valid_to);
  const out = {
    id: o.id, offer: str(o.label) ? o.label : o.issuer, issuer: o.issuer, app: appName(o), deal: dealText(o),
    benefit: o.value, cap: o.cap_text, days: falsy(o.days) ? "not stated in the terms" : o.days, day_basis: o.day_basis,
    min_tickets: o.min_tickets, monthly_limit: o.monthly_limit, conditions: o.quota_note,
    requires_purchase: o.requires_purchase, code: o.code, valid_to: o.valid_to,
    days_left: end !== null ? Math.round((end - istDay(now)) / 86400000) : null,
    ends: end !== null ? null : (str(o.validity_note) ? o.validity_note : "no end date in the terms"), checked_at: o.checked_at,
    cards: o.card_variants, excludes: o.excludes, source_url: o.source_url, url: o.url,
  };
  out.plan_text = planText(o);
  out.whatsapp_url = "https://wa.me/?text=" + quote(out.plan_text);
  if (note) out.freshness = note;
  return Object.fromEntries(Object.entries(out).filter(([, v]) => !(v == null || v === "" || (Array.isArray(v) && !v.length))));
}

function cmp(a, b) {                                   // compare Python-style tuples
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

function findOffers(feed, args, now) {
  const day = !falsy(args.day) ? dayKey(args.day, now) : null;
  let app = null;
  if (!falsy(args.app)) {
    app = APP_WORDS[String(args.app).trim().toLowerCase()];
    if (!app) throw new ToolError("app must be BookMyShow, District or PVR INOX");
  }
  const bank = str(args.bank).trim().toLowerCase();
  const words = str(args.query).toLowerCase().split(/\s+/).filter(Boolean);
  const events = !falsy(args.include_events);
  const hits = [];
  for (const o of feed.offers || []) {
    const [ok, note] = live(o, now);
    if (!ok || (o.category === "events" && !events)) continue;
    if (app && appOf(o) !== app) continue;
    if (bank && !str(o.issuer).toLowerCase().includes(bank) && !str(o.label).toLowerCase().includes(bank)) continue;
    const days = (falsy(o.days) ? [] : o.days).map((d) => String(d).toLowerCase());
    if (day && days.length && !days.includes("any") && !days.includes(day)) continue;
    const val = isObj(o.value) ? o.value : {};
    let hay = [...["label", "issuer", "cap_text", "quota_note", "kind", "platform"].map((k) => str(o[k])),
               ...Object.entries(val).map(([k, v]) => `${k} ${v}`),
               ...(falsy(o.card_variants) ? [] : o.card_variants).map(String)].join(" ").toLowerCase();
    if (o.kind === "bogo") hay += " bogo buy 1 get 1 buy one get one 2nd ticket free";
    if (words.some((w) => !hay.includes(w))) continue;
    hits.push(summary(o, now, note));
  }
  hits.sort((x, y) => cmp([x.days_left == null ? 1 : 0, x.days_left || 0, String(x.id)],
                          [y.days_left == null ? 1 : 0, y.days_left || 0, String(y.id)]));
  const out = { count: hits.length, offers: hits, generated_at: feed.generated_at ?? null, note: NOTE };
  if (day) {
    out.day = { key: day, rule: "An offer matches when its terms name that day or every day. Offers whose terms " +
      "name no day are included with days \"not stated in the terms\": say so, don't promise that day. `day_basis` says " +
      "whether the day is the booking day or the show day." };
  }
  if (!hits.length) {
    out.hint = "No checked offer matches. FDFS lists only offers it has checked; there may be others it hasn't " +
      "verified. See https://bookmyfdfs.in/ for everything that passes its checks.";
  }
  return out;
}

function matchCards(feed, args, now) {
  const cards = args.cards;
  if (!Array.isArray(cards) || !cards.length || !cards.every((c) => typeof c === "string" && c.trim())) {
    throw new ToolError("cards must be a list of card names, for example [\"Axis My Zone\", \"ICICI\"]");
  }
  const base = {};
  for (const k of ["app", "day", "include_events"]) if (k in args) base[k] = args[k];
  const pool = findOffers(feed, base, now).offers;
  const byId = {};
  for (const o of feed.offers || []) byId[o.id] = o;
  const tickets = args.tickets;
  const rows = [];
  for (const card of cards.slice(0, 10)) {
    const hits = [];
    for (const s of pool) {
      const o = byId[s.id] || {};
      const how = cardMatch(o, card);
      if (!how) continue;
      if (Number.isInteger(tickets) && Number.isInteger(o.min_tickets) && tickets < o.min_tickets) continue;
      hits.push({ ...s, card_match: how });
    }
    const k = (h) => [RANK[h.card_match], -value(byId[h.id] || {}), h.days_left || 0];
    hits.sort((a, b) => cmp(k(a), k(b)));
    const row = { card, count: hits.length, offers: hits };
    if (!hits.length) row.hint = "No checked offer for this card with these filters.";
    else if (hits[0].card_match in HINTS) row.hint = HINTS[hits[0].card_match];
    rows.push(row);
  }
  const out = { cards: rows, generated_at: feed.generated_at ?? null, note: NOTE };
  const firsts = rows.filter((r) => r.offers.length).map((r) => r.offers[0]);
  if (firsts.length) {
    const k = (h) => [RANK[h.card_match], -value(byId[h.id] || {})];
    out.best = firsts.reduce((a, b) => (cmp(k(b), k(a)) < 0 ? b : a)).id;
  }
  return out;
}

function getOffer(feed, args, now) {
  const oid = str(args.id).trim();
  for (const o of feed.offers || []) {
    if (o.id === oid) {
      const [ok, note] = live(o, now);
      const rec = { ...o, status: ok ? "current" : "ended" };
      if (note) rec.freshness = note;
      rec.plan_text = planText(o);
      rec.note = NOTE;
      return rec;
    }
  }
  throw new ToolError(`No checked offer with id ${pyRepr(oid)}. Use find_offers to list ids.`);
}

function listBanks(feed, args, now) {
  const banks = new Map();
  for (const o of feed.offers || []) {
    if (!live(o, now)[0]) continue;
    const name = str(o.issuer) ? o.issuer : "Other";
    if (!banks.has(name)) banks.set(name, { issuer: name, offers: 0, apps: new Set() });
    const b = banks.get(name);
    b.offers += 1;
    b.apps.add(appOf(o) in APPS ? APPS[appOf(o)] : String(o.platform ?? "None"));
  }
  const rows = [...banks.values()].sort((a, b) => cmp([-a.offers, a.issuer], [-b.offers, b.issuer]))
    .map((b) => ({ ...b, apps: [...b.apps].sort() }));
  return { count: rows.length, banks: rows, generated_at: feed.generated_at ?? null, note: NOTE };
}

const HANDLERS = { find_offers: findOffers, match_cards: matchCards, get_offer: getOffer, list_banks: listBanks };

function readable(name, data) {
  const line = (h) => {
    const bits = [`${h.offer} on ${h.app}: ${h.deal}`];
    if (Array.isArray(h.days)) bits.push(h.days.includes("any") ? "any day" : h.days.join(", "));
    if (h.card_match) bits.push(h.card_match);
    if (h.valid_to) bits.push(`until ${h.valid_to}`);
    if (h.freshness) bits.push(h.freshness.split(":")[0].toLowerCase());
    return "- " + bits.join(", ") + `. ${h.url}`;
  };
  let head, lines;
  if (name === "find_offers") {
    lines = data.offers.slice(0, 15).map(line);
    if (!lines.length) lines = [data.hint ?? ""];
    head = `${data.count} checked offers from FDFS (bookmyfdfs.in):`;
  } else if (name === "match_cards") {
    lines = [];
    for (const r of data.cards) {
      const n = r.count;
      lines.push(`${r.card}: ` + (n ? `${n} offer${n !== 1 ? "s" : ""}` : (r.hint ?? "none")));
      lines.push(...r.offers.slice(0, 5).map(line));
    }
    head = "Card matches from FDFS (bookmyfdfs.in):";
  } else return "";
  return head + "\n" + lines.join("\n") + "\nRead the terms before paying. Full data follows as JSON.";
}

// ---- JSON-RPC ----------------------------------------------------------------------------------------------------
export async function handle(msg, env) {
  if (!isObj(msg)) return { jsonrpc: "2.0", id: null, error: { code: -32600, message: "Invalid request" } };
  const mid = msg.id ?? null, method = msg.method;
  const params = falsy(msg.params) ? {} : msg.params;
  if (!("id" in msg)) return null;                     // a notification: nothing to answer
  const ok = (result) => ({ jsonrpc: "2.0", id: mid, result });
  const err = (code, message) => ({ jsonrpc: "2.0", id: mid, error: { code, message } });
  if (method === "initialize") {
    const want = params.protocolVersion;
    return ok({ protocolVersion: PROTOCOLS.includes(want) ? want : PROTOCOLS[0],
                capabilities: { tools: { listChanged: false } },
                serverInfo: { name: "fdfs", title: "FDFS movie ticket offers", version: VERSION },
                instructions: NOTE + " Spotted (unverified) leads are never returned." });
  }
  if (method === "ping") return ok({});
  if (method === "tools/list") return ok({ tools: TOOLS });
  if (method === "tools/call") {
    const name = params.name;
    const args = falsy(params.arguments) ? {} : params.arguments;
    if (!Object.prototype.hasOwnProperty.call(HANDLERS, name)) return err(-32602, `Unknown tool: ${name ?? "None"}`);
    if (!isObj(args)) return err(-32602, "arguments must be an object");
    let data;
    try {
      data = HANDLERS[name](await getFeed(env), args, nowMs(env));
    } catch (e) {
      if (e instanceof ToolError) return ok({ content: [{ type: "text", text: e.message }], isError: true });
      throw e;
    }
    const content = [{ type: "text", text: JSON.stringify(data, null, 1) }];
    const lead = readable(name, data);
    if (lead) content.unshift({ type: "text", text: lead });
    return ok({ content, structuredContent: data });
  }
  return err(-32601, `Method not found: ${method ?? "None"}`);
}

// ---- HTTP --------------------------------------------------------------------------------------------------------
const CORS = {
  "Access-Control-Allow-Origin": "*",                  // public, read-only data with no cookies or auth
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, Mcp-Session-Id, Mcp-Protocol-Version, Last-Event-ID",
  "Access-Control-Expose-Headers": "Mcp-Session-Id",
};
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...CORS } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (url.pathname === "/" && request.method === "GET") {
      return new Response("FDFS MCP server. POST JSON-RPC to /mcp. Setup: https://bookmyfdfs.in/agents/\n",
        { headers: { "Content-Type": "text/plain; charset=utf-8", ...CORS } });
    }
    if (url.pathname !== "/mcp") return new Response("Not found\n", { status: 404, headers: CORS });
    if (request.method !== "POST") {                   // no server-sent event stream: every answer is one JSON reply
      return new Response("Method not allowed\n", { status: 405, headers: { Allow: "POST, OPTIONS", ...CORS } });
    }
    const raw = await request.text();
    if (raw.length > MAX_BODY) return json({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "Request too large" } }, 413);
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400);
    }
    if (Array.isArray(msg)) {                          // older clients may batch
      const out = (await Promise.all(msg.map((m) => handle(m, env)))).filter(Boolean);
      return out.length ? json(out) : new Response(null, { status: 202, headers: CORS });
    }
    const resp = await handle(msg, env);
    return resp ? json(resp) : new Response(null, { status: 202, headers: CORS });
  },
};

export { CONSTANTS };
