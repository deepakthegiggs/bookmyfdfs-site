#!/bin/sh
# FDFS deploy: build -> tests -> publish dist/ to the publish branch -> IndexNow ping of changed URLs only.
# Runs ONLY when the lead runs it at launch. Google finds the sitemap via robots.txt and Search Console
# (Google's sitemap ping endpoint is retired), so there's no Google ping here.
#
#   scripts/deploy.sh --dry-run                  # build + tests, show what would publish and be pinged; no git, no network
#   scripts/deploy.sh --branch main              # build + tests + commit dist/ to main (local only)
#   scripts/deploy.sh --branch main --push       # launch: + push (GitHub Pages serves main), then IndexNow --send
# Every publish keeps CNAME (exactly bookmyfdfs.in) and .nojekyll, or it aborts.
#
# Env (for tests and CI): FDFS_SOURCE (default: data/offers.source.txt), FDFS_TEST_CMD (default: the unittest suite), FDFS_OUT (default: dist),
# FDFS_STATE (default: data/build-state.json), FDFS_BUILD_ARGS (extra args, e.g. --no-og).
set -eu
cd "$(dirname "$0")/.."
DRY=0; BRANCH=""; PUSH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --branch) BRANCH="$2"; shift ;;
    --push) PUSH=1 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
OUT=${FDFS_OUT:-dist}
PUBLISHED_STATE=${FDFS_STATE:-data/build-state.json}   # what is live: content hashes + lastmod per URL
STATE=$(mktemp)                                         # this run works on a copy; it replaces the published
if [ -f "$PUBLISHED_STATE" ]; then cp "$PUBLISHED_STATE" "$STATE"; else echo '{}' > "$STATE"; fi   # state only after a push
TEST_CMD=${FDFS_TEST_CMD:-"python3 -m unittest discover -s tests"}

# Honesty guard: the site states "Checked … <time>". Data from a fixture replay was never checked live.
SOURCE=${FDFS_SOURCE:-data/offers.source.txt}
if [ ! -f "$SOURCE" ]; then
  echo "ABORT: $SOURCE is missing: can't tell whether the export comes from a live check. Nothing published." >&2
  exit 1
fi
if grep -qiE "fixture|replay" "$SOURCE"; then
  echo "ABORT: $SOURCE says the export came from a fixture/replay, not a live check. Nothing published." >&2
  exit 1
fi

# Spotted leads (decision 135) must be real web finds: the test fixture's placeholder sources never publish.
SPOTTED=${FDFS_SPOTTED:-data/spotted.json}
if [ -f "$SPOTTED" ] && grep -qiE '://[^"/]*example\.(com|org|net)' "$SPOTTED"; then
  echo "ABORT: $SPOTTED has placeholder (example.*) sources: it's a fixture, not real leads. Nothing published." >&2
  exit 1
fi

echo "== 1/4 build"
python3 gen/fdfs_site.py --snapshot --out "$OUT" --state "$STATE" --spotted "$SPOTTED" ${FDFS_BUILD_ARGS:-}

echo "== 2/4 tests"
if ! sh -c "$TEST_CMD"; then
  echo "ABORT: tests failed. Nothing published, nothing pinged." >&2
  exit 1
fi

# The custom domain and HTTPS break if CNAME or .nojekyll go missing from the published tree.
if [ "$(cat "$OUT/CNAME" 2>/dev/null)" != "bookmyfdfs.in" ] || [ ! -f "$OUT/.nojekyll" ]; then
  echo "ABORT: $OUT/CNAME must be exactly bookmyfdfs.in and $OUT/.nojekyll must exist. Nothing published." >&2
  exit 1
fi

CHANGED=$(grep -c . "$OUT/.changed-urls.txt" || true)
if [ "$DRY" = 1 ]; then
  echo "== dry run: would publish $(find "$OUT" -type f | wc -l | tr -d ' ') files and ping $CHANGED changed URL(s):"
  cat "$OUT/.changed-urls.txt"
  exit 0
fi
[ -n "$BRANCH" ] || { echo "ABORT: --branch is required (or use --dry-run)" >&2; exit 2; }
[ "$BRANCH" != "s1-generator" ] || { echo "ABORT: never publish onto the source branch" >&2; exit 2; }

echo "== 3/4 publish $OUT/ to branch $BRANCH"
WT=$(mktemp -d)
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git worktree add -q "$WT" "$BRANCH"
else
  git worktree add -q --detach "$WT" && (cd "$WT" && git checkout -q --orphan "$BRANCH" && git rm -rqf . >/dev/null 2>&1 || true)
fi
find "$WT" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$OUT"/. "$WT"/
rm -f "$WT/.changed-urls.txt"
[ "$(cat "$WT/CNAME")" = "bookmyfdfs.in" ] && [ -f "$WT/.nojekyll" ] || { echo "ABORT: CNAME/.nojekyll missing in publish tree" >&2; git worktree remove --force "$WT"; exit 1; }
SRC=$(git rev-parse --short HEAD)
(cd "$WT" && git add -A && { git diff --cached --quiet && echo "no file changes to publish"; } || git commit -q -m "Publish site from $SRC")
if [ "$PUSH" = 1 ]; then
  (cd "$WT" && git push -q origin "$BRANCH")
  cp "$STATE" "$PUBLISHED_STATE"
  git add "$PUBLISHED_STATE" data/history data/offers.json data/offers.source.txt $( [ -f data/spotted.json ] && echo data/spotted.json ) $( [ -f data/discover-spend.json ] && echo data/discover-spend.json ) $( [ -f data/carry-state.json ] && echo data/carry-state.json ) && \
    git commit -q -m "Published data and state after deploy of $SRC" || true
  echo "== 4/4 IndexNow ($CHANGED changed URL(s))"
  python3 scripts/indexnow_ping.py --dist "$OUT" --send
else
  echo "== 4/4 skipped IndexNow: not pushed (add --push to go live and ping)"
fi
git worktree remove --force "$WT"
