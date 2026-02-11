#!/bin/bash
# Wait for CI to pass, then poll health endpoint until new build is live.
# Usage: ./scripts/wait-deploy.sh [expected_build]
# If no arg, reads BUILD_NUMBER file.

set -euo pipefail

REPO="CIRISAI/CIRISNode"
HEALTH_URL="https://node.ciris.ai/api/v1/health"
POLL_INTERVAL=30

# Determine expected build number
if [ -n "${1:-}" ]; then
    EXPECTED="$1"
else
    EXPECTED=$(cat "$(git rev-parse --show-toplevel)/BUILD_NUMBER" | tr -d '[:space:]')
fi

echo "Target build: $EXPECTED"

# Phase 1: Wait for CI to complete
echo ""
echo "=== Phase 1: Waiting for CI ==="
while true; do
    # Get latest run status
    RUN_INFO=$(gh run list --repo "$REPO" --limit 1 --json status,conclusion,name,databaseId 2>/dev/null || echo "[]")
    STATUS=$(echo "$RUN_INFO" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r[0]['status'] if r else 'unknown')" 2>/dev/null)
    CONCLUSION=$(echo "$RUN_INFO" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r[0].get('conclusion') or '' if r else '')" 2>/dev/null)

    if [ "$STATUS" = "completed" ] && [ "$CONCLUSION" = "success" ]; then
        echo "$(date '+%H:%M:%S') CI passed"
        break
    elif [ "$STATUS" = "completed" ] && [ "$CONCLUSION" != "success" ]; then
        echo "$(date '+%H:%M:%S') CI FAILED ($CONCLUSION) — aborting"
        exit 1
    else
        echo "$(date '+%H:%M:%S') CI status: $STATUS — waiting..."
        sleep 15
    fi
done

# Phase 2: Wait for Watchtower to deploy the new build
echo ""
echo "=== Phase 2: Waiting for Watchtower deploy ==="
while true; do
    BUILD=$(curl -sf "$HEALTH_URL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('build',0))" 2>/dev/null || echo "?")
    if [ "$BUILD" = "$EXPECTED" ]; then
        echo "$(date '+%H:%M:%S') Build $EXPECTED is live!"
        break
    else
        echo "$(date '+%H:%M:%S') Current build: $BUILD (waiting for $EXPECTED)"
        sleep "$POLL_INTERVAL"
    fi
done
