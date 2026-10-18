#!/usr/bin/env bash
# Poll a health URL until it answers 200 or the timeout runs out.
# Usage: wait-for-health.sh <url> [timeout-seconds]
set -euo pipefail

url=${1:?usage: wait-for-health.sh <url> [timeout-seconds]}
timeout=${2:-60}

# `--max-time` and a wall-clock deadline: without them each hanging request stretched the
# timeout, so "30" meant 30 attempts rather than 30 seconds.
deadline=$((SECONDS + timeout))
while ((SECONDS < deadline)); do
    if curl -fsS --max-time 5 -o /dev/null "$url" 2>/dev/null; then
        echo "healthy after ${SECONDS}s: $url"
        exit 0
    fi
    sleep 1
done

echo "not healthy after ${timeout}s: $url" >&2
exit 1
