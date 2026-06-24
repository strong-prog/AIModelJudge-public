#!/usr/bin/env bash
# AIModelJudge — OWASP ZAP scan wrapper
# Usage: ./scripts/zap-scan.sh [target_url] [report_prefix]
# Default target: http://127.0.0.1:9651

set -euo pipefail

TARGET="${1:-http://127.0.0.1:9651}"
PREFIX="${2:-zap-report}"

echo "=== OWASP ZAP Baseline Scan ==="
echo "Target: $TARGET"
echo "Output: ${PREFIX}.html / ${PREFIX}.md"
echo ""

# Kill any existing zap containers
docker rm -f zap-scan 2>/dev/null || true

# Run ZAP baseline scan
# -- zap2docker-stable image includes zap-baseline.py
docker run --rm --name zap-scan \
  --network host \
  -v "$(pwd):/zap/wrk:rw" \
  -t owasp/zap2docker-stable:latest \
  zap-baseline.py \
    -t "$TARGET" \
    -r "${PREFIX}.html" \
    -w "${PREFIX}.md" \
    --timeout 120 \
    -z "-config api.disablekey=true" \
  || {
    EXIT_CODE=$?
    echo ""
    echo "ZAP scan completed with exit code: $EXIT_CODE"
    echo "Reports saved: ${PREFIX}.html, ${PREFIX}.md"
    echo ""
    echo "=== WARNING ==="
    echo "High/Critical alerts found! Review the report."
    echo "=== WARNING ==="
    exit $EXIT_CODE
  }

echo ""
echo "=== ZAP scan passed (no high/critical alerts) ==="
ls -la "${PREFIX}.html" "${PREFIX}.md" 2>/dev/null
