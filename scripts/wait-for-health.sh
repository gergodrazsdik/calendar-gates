#!/usr/bin/env bash
# Poll a health URL until it answers 200 or the timeout runs out.
# Usage: wait-for-health.sh <url> [timeout-seconds]
set -euo pipefail

url=${1:?usage: wait-for-health.sh <url> [timeout-seconds]}
timeout=${2:-60}

for ((i = 0; i < timeout; i++)); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
        echo "healthy after ${i}s: $url"
        exit 0
    fi
    sleep 1
done

echo "not healthy after ${timeout}s: $url" >&2
exit 1
