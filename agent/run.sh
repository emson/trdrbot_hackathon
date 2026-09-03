#!/usr/bin/env bash
# One tick. Point launchd/cron at this.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run trdrbot tick "$@"
