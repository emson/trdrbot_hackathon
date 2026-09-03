#!/usr/bin/env bash
# Refresh every figure the submission deck carries, reviewably, in one
# command (notes/027). Run this by hand before submitting - never on a loop.
#
# Unlike publish.sh, this WRITES to tracked source files: docs/deck.html and
# docs/deck.pdf. That is deliberate and is the whole point - the deck is the
# submission artifact, and "one command, one set of figures" means this
# script is the one place a human re-derives every number in it and then
# reviews the diff before committing. Nothing here commits, pushes, or
# deploys; those stay explicit, separate, human decisions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT="$ROOT/agent"
WEB="$ROOT/web"
DOCS="$ROOT/docs"
SNAPSHOT="$WEB/src/lib/data/snapshot.json"
DECK="$DOCS/deck.html"
PDF="$DOCS/deck.pdf"
PDF_PORT=8899

cd "$AGENT"

# --refresh-tests: the one thing site_export.py deliberately does NOT do on
# every export, because it needs a subprocess that imports the whole test
# suite. The release path is exactly the case that can afford it, and the
# deck cites the test count, so this is where it earns being current.
echo "[release] exporting the record (refreshing the test count)"
uv run trdrbot site export --refresh-tests

echo "[release] refreshing the deck's figures in place"
node "$WEB/scripts/inject-figures.mjs" "$SNAPSHOT" "$DECK" --write

echo "[release] regenerating the PDF"
# file:// breaks the deck's webfonts (measured, see web/CLAUDE.md), so the
# deck is served locally rather than opened directly. The port is torn down
# unconditionally, whether the render succeeds or not.
PDF_PID=""
cleanup() { [ -n "$PDF_PID" ] && kill "$PDF_PID" 2>/dev/null || true; }
trap cleanup EXIT

if lsof -i ":$PDF_PORT" >/dev/null 2>&1; then
	echo "[release] port $PDF_PORT is already in use - leaving the PDF step to " \
	     "whatever is already serving it, and hoping it is docs/"
else
	# `--directory`, not `(cd "$DOCS" && ...) &` - backgrounding a subshell
	# makes `$!` the SUBSHELL's pid, not the python3 process actually holding
	# the port, so `kill "$PDF_PID"` in cleanup() silently killed nothing and
	# left the server running (found by testing this script for real, not
	# assumed: the port was still listening after a full run completed).
	python3 -m http.server --directory "$DOCS" "$PDF_PORT" >/dev/null 2>&1 &
	PDF_PID=$!
fi

READY=""
for _ in $(seq 1 20); do
	if curl -s -o /dev/null "http://localhost:$PDF_PORT/deck.html"; then
		READY=1
		break
	fi
	sleep 0.25
done
if [ -z "$READY" ]; then
	echo "[release] the local server for the PDF render never came up - refusing"
	exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
	echo "[release] Google Chrome not found at the expected path - skipping the PDF." \
	     "The deck itself is already refreshed; regenerate the PDF by hand (see web/CLAUDE.md)."
else
	"$CHROME" --headless --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 \
		--print-to-pdf="$PDF" "http://localhost:$PDF_PORT/deck.html"
	echo "[release] wrote $PDF"
fi

echo "[release] syncing the static passthrough copy and building the site locally"
node "$WEB/scripts/sync-static.mjs"
(cd "$WEB" && npm run build) >/dev/null

echo
echo "[release] done. Review before committing:"
echo "    git diff docs/deck.html"
echo "    open docs/deck.pdf"
echo "Then commit, and deploy when ready:"
echo "    ./scripts/publish.sh"
