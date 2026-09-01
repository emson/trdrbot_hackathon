#!/usr/bin/env bash
# Re-export the agent's record, rebuild the site, and deploy it - or do
# nothing and say so. Idempotent, lock-guarded, never touches the trading
# loop. Run this in a loop (see the header comment below) or once by hand.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/web"
LOCK="$ROOT/data/.publish.lock"
LOG="$ROOT/data/publish_log.jsonl"
SNAPSHOT="$WEB/src/lib/data/snapshot.json"

log_row() {
	# {ts, status, detail}
	local status="$1" detail="$2"
	printf '{"ts":"%s","status":"%s","detail":%s}\n' \
		"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" "$(printf '%s' "$detail" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
		>> "$LOG"
}

exec 9>"$LOCK"
if ! flock -n 9; then
	echo "[publish] another publish is already running - skipping"
	exit 0
fi

cd "$ROOT"

echo "[publish] refreshing the coach report"
uv run trdrbot report || true  # best-effort; never blocks the site export

BEFORE_HASH=""
[ -f "$SNAPSHOT" ] && BEFORE_HASH="$(shasum -a 256 "$SNAPSHOT" | cut -d' ' -f1)"

echo "[publish] exporting the site snapshot"
if ! uv run trdrbot site export; then
	echo "[publish] export refused (guard tripped) - not deploying"
	log_row "refused" "site export guard tripped - see stderr above"
	exit 1
fi

AFTER_HASH="$(shasum -a 256 "$SNAPSHOT" | cut -d' ' -f1)"
if [ "$BEFORE_HASH" = "$AFTER_HASH" ]; then
	echo "[publish] no change since last export - nothing to deploy"
	log_row "noop" "snapshot unchanged"
	exit 0
fi

echo "[publish] syncing static passthrough documents"
node "$WEB/scripts/sync-static.mjs"

echo "[publish] building the site"
(cd "$WEB" && npm run build)

echo "[publish] verifying the build"
if [ ! -s "$WEB/build/index.html" ]; then
	echo "[publish] build/index.html missing or empty - refusing to deploy"
	log_row "build_failed" "index.html missing or empty"
	exit 1
fi
if [ ! -f "$WEB/build/ledger.html" ]; then
	echo "[publish] build/ledger.html missing - refusing to deploy"
	log_row "build_failed" "ledger index missing"
	exit 1
fi

echo "[publish] deploying to Cloudflare Pages"
if (cd "$WEB" && npx wrangler pages deploy build --project-name trdrbot --commit-dirty=true); then
	log_row "deployed" "hash ${AFTER_HASH:0:12}"
	echo "[publish] done"
else
	echo "[publish] deploy failed - the previous live deployment is untouched"
	log_row "deploy_failed" "wrangler pages deploy returned non-zero"
	exit 1
fi
