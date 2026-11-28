// Test harness for gen/mcp-worker/worker.js (tests/test_mcp_worker.py). Reads {feed, now, messages, http} as JSON on
// stdin, serves the feed to the worker's fetch() from memory, and prints the answers as JSON. No network.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const input = JSON.parse(readFileSync(0, "utf8"));
const feedText = input.feed === null ? null : JSON.stringify(input.feed);
let fetched = 0;
globalThis.fetch = async (url) => {
  fetched += 1;
  if (feedText === null) throw new TypeError("network down");
  return new Response(feedText, { status: 200, headers: { "Content-Type": "application/json" } });
};
const mod = await import(pathToFileURL(process.argv[2]).href);
const env = { FDFS_NOW: input.now, FDFS_FEED: "https://bookmyfdfs.in/offers.json" };
const rpc = [];
for (const m of input.messages || []) rpc.push(await mod.handle(m, env));
const http = [];
for (const h of input.http || []) {
  const r = await mod.default.fetch(new Request("https://fdfs-mcp.example.workers.dev" + h.path,
    { method: h.method, headers: h.headers || {}, body: h.body ?? undefined }), env);
  http.push({ status: r.status, headers: Object.fromEntries(r.headers), body: await r.text() });
}
process.stdout.write(JSON.stringify({ rpc, http, fetched }));
