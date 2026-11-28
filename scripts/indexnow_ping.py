"""Ping IndexNow (Bing, Yandex, Naver, Seznam, Yep; not Google) with the pages whose content changed in
this build. Run it ONLY as the last step of a deploy, after the new dist/ is live. Never on a cron by itself.

    python3 scripts/indexnow_ping.py            # dry run: prints what it would send
    python3 scripts/indexnow_ping.py --send     # sends (after deploy)

It reads dist/.changed-urls.txt (written by the generator: pages whose content hash changed) and
data/indexnow-key.txt (the key file is published at /<key>.txt by the build). Nothing changed -> no ping.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args(argv)
    urls = [u.strip() for u in (Path(a.dist) / ".changed-urls.txt").read_text().splitlines() if u.strip()]
    if not urls:
        print("no changed pages: nothing to ping")
        return 0
    key = (ROOT / "data/indexnow-key.txt").read_text().strip()
    host = urlparse(urls[0]).netloc
    if not (Path(a.dist) / f"{key}.txt").exists():
        sys.exit("key file missing from dist: build first")
    body = {"host": host, "key": key, "keyLocation": f"https://{host}/{key}.txt", "urlList": urls[:10000]}
    if not a.send:
        print("dry run, would POST to https://api.indexnow.org/indexnow:\n" + json.dumps(body, indent=1))
        return 0
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("IndexNow:", r.status, "for", len(urls), "URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
