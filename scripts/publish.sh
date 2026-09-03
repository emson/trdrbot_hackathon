#!/usr/bin/env bash
# Re-export the agent's record, rebuild the site, and deploy it - or do
# nothing and say so. Idempotent, lock-guarded, never touches the trading
# loop. Run this in a loop (see the header comment below) or once by hand.
#
#   ./scripts/publish.sh          the loop's form: deploys only if the record moved
#   ./scripts/publish.sh --force  by hand, after a code or copy change: deploys
#                                 even when the record is unchanged, and still
#                                 re-exports first - so a push never carries
#                                 yesterday's figures next to today's copy
set -euo pipefail

FORCE=""
for arg in "$@"; do
	case "$arg" in
		--force) FORCE=1 ;;
		*) echo "usage: $0 [--force]" >&2; exit 2 ;;
	esac
done

# This script spans both projects - it reads the agent's record and writes the
# website - so it lives at the repo root rather than inside either one.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT="$ROOT/agent"
WEB="$ROOT/web"
LOCK="$AGENT/data/.publish.lock"
LOG="$AGENT/data/publish_log.jsonl"
SNAPSHOT="$WEB/src/lib/data/snapshot.json"

log_row() {
	# {ts, status, detail}
	local status="$1" detail="$2"
	printf '{"ts":"%s","status":"%s","detail":%s}\n' \
		"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" "$(printf '%s' "$detail" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
		>> "$LOG"
}

# A DIRECTORY is the lock, because `mkdir` is atomic on every POSIX filesystem
# and needs no external tool. The previous spelling was `flock -n 9`, and
# `flock` does not exist on macOS - so `if ! flock` was taking the "someone else
# is publishing" branch on a `command not found`, and this script exited 0
# announcing a conflict that could not happen. It had never once published from
# this machine. Failing OPEN on a missing binary is bad; failing open into a
# message that says the opposite is worse, and it is the exact bug class this
# project keeps finding.
LOCKDIR="$LOCK.d"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
	# Stale locks are breakable: a crashed publish must not wedge the site
	# forever, and there is no pid in a directory to check liveness with.
	if [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
		echo "[publish] breaking a stale lock older than 30 minutes"
		rm -rf "$LOCKDIR" && mkdir "$LOCKDIR"
	else
		echo "[publish] another publish is already running - skipping"
		exit 0
	fi
fi
trap 'rm -rf "$LOCKDIR"' EXIT

# `uv run` resolves its project from the working directory, and the agent's
# `pyproject.toml` now lives in `agent/`. From the repo root there is no
# project to find and every `uv run` below would fail.
cd "$AGENT"

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
	if [ -z "$FORCE" ]; then
		echo "[publish] no change since last export - nothing to deploy"
		log_row "noop" "snapshot unchanged"
		exit 0
	fi
	echo "[publish] record unchanged, but --force given - deploying the site anyway"
fi

echo "[publish] syncing static passthrough documents"
node "$WEB/scripts/sync-static.mjs"

# The STATIC COPY only (notes/027) - sync-static just regenerated it fresh
# from docs/deck.html's own baked (possibly stale-by-now) text, and this
# rewrites its figures from the snapshot that export just wrote. docs/deck.html
# itself, the tracked SOURCE, is never touched here: this script runs on a
# loop, and writing to a tracked file every cycle would dirty the working
# tree constantly for no reviewable reason. Refreshing the deck SOURCE is
# `scripts/release.sh`'s job, run by hand, reviewed, and committed
# deliberately.
echo "[publish] refreshing the deck's live figures (static copy only)"
if ! node "$WEB/scripts/inject-figures.mjs" "$SNAPSHOT" "$WEB/static/deck.html" --write; then
	echo "[publish] figure injection refused (see the report above) - not deploying"
	log_row "refused" "inject-figures could not resolve every tagged figure"
	exit 1
fi

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

# `--branch main` is what makes this a PRODUCTION deploy rather than a preview.
# For a direct upload the branch is only a label Cloudflare matches against the
# project's production branch; without it wrangler labels the deploy with the
# current git branch, and work done on a feature branch lands on a preview URL
# that trdrbot.com never serves. This script is called `publish` - publishing is
# its whole job, so it says so rather than inheriting an answer from git.
#
# The project name is `trdrbot-com`, not `trdrbot`. That was wrong here from the
# start and nobody saw it, because the broken lock above returned before ever
# reaching this line: one silent no-op hiding another.
echo "[publish] deploying to Cloudflare Pages (production)"
if (cd "$WEB" && npx wrangler pages deploy build --project-name trdrbot-com \
		--branch main --commit-dirty=true); then
	log_row "deployed" "hash ${AFTER_HASH:0:12}"
	echo "[publish] done"
else
	echo "[publish] deploy failed - the previous live deployment is untouched"
	log_row "deploy_failed" "wrangler pages deploy returned non-zero"
	exit 1
fi
