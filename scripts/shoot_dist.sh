#!/bin/sh
# Screenshots of generated pages (never publishes). Usage: scripts/shoot_dist.sh <dist> <outdir> <width> <theme> <path>...
# Serves a temporary copy of dist (plus an exact-width iframe frame) on a free port, so a stale server can't serve old files.
set -e
DIST=$1; OUT=$2; W=$3; T=$4; shift 4
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP=$(mktemp -d); cp -R "$DIST"/. "$TMP"/; cp "$(dirname "$0")/../preview/shots/frame.html" "$TMP/__frame.html"
mkdir -p "$OUT"
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$TMP" >/dev/null 2>&1 & SRV=$!
trap 'kill $SRV 2>/dev/null; rm -rf "$TMP"' EXIT
sleep 1
curl -sf "http://127.0.0.1:$PORT/__frame.html" >/dev/null || { echo "screenshot server failed to start" >&2; exit 1; }
for P in "$@"; do
  NAME=$(echo "$P" | sed 's#^/##; s#/$##; s#/#-#g'); [ -z "$NAME" ] && NAME=home
  "$CH" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=4000 \
    --window-size=$W,7000 --screenshot="$OUT/$NAME-$W-$T.png" \
    "http://127.0.0.1:$PORT/__frame.html?w=$W&h=7000&src=$P%3Ftheme%3D$T" >/dev/null 2>&1
done
python3 - "$OUT" <<PY
import sys,glob
from PIL import Image
for f in glob.glob(sys.argv[1]+"/*.png"):
    im=Image.open(f).convert("RGB"); w,h=im.size; px=im.load(); y=h-1
    while y>0 and px[w//2,y]==(136,136,136) and px[2,y]==(136,136,136): y-=1
    im.crop((0,0,w,y+1)).save(f, optimize=True)
PY
