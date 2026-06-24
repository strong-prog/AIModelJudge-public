#!/usr/bin/env bash
# AIModelJudge — Load Test
# Usage: bash tests/load_test.sh [base_url]
# Delegates to tests/load_test.py when available (async, 5 scenarios).
# Falls back to simple curl-based concurrent test.

BASE="${1:-http://127.0.0.1:9651}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_LOAD_TEST="$SCRIPT_DIR/load_test.py"

if [ -f "$PY_LOAD_TEST" ] && command -v python3 &>/dev/null && python3 -c "import aiohttp" 2>/dev/null; then
    echo "=== Using async load_test.py (full suite) ==="
    PYTHONPATH="$SCRIPT_DIR/..:$SCRIPT_DIR/../web:$SCRIPT_DIR/../services/shared" \
        exec python3 "$PY_LOAD_TEST" "$BASE"
fi

# ── Fallback: simple curl-based test ──
set -euo pipefail
echo "=== AIModelJudge Load Test (curl fallback) ==="
CONCURRENT=5
echo "=== AIModelJudge Load Test: $CONCURRENT concurrent /chat requests ==="
echo "Target: $BASE"
echo ""

declare -a PIDS
declare -a RESULTS
START=$(date +%s.%N)

for i in $(seq 1 $CONCURRENT); do
    (
        code=$(curl -s -o /tmp/amj_load_$$_$i.txt -w "%{http_code}" \
            -X POST "$BASE/chat" \
            -H 'Content-Type: application/json' \
            -d "{\"message\":\"Say $i in one word\"}" \
            --max-time 60 2>/dev/null || echo "000")
        echo "$i:$code" > /tmp/amj_load_result_$$_$i.txt
    ) &
    PIDS+=($!)
done

# Wait for all
for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
done

END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc 2>/dev/null || echo "N/A")

PASS=0
FAIL=0
echo "Results:"
for i in $(seq 1 $CONCURRENT); do
    result=$(cat /tmp/amj_load_result_$$_$i.txt 2>/dev/null || echo "$i:???")
    code="${result#*:}"
    if [ "$code" = "200" ]; then
        echo "  PASS  request $i → $code"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  request $i → $code"
        FAIL=$((FAIL + 1))
    fi
    rm -f /tmp/amj_load_$$_$i.txt /tmp/amj_load_result_$$_$i.txt
done

echo ""
echo "Time: ${ELAPSED}s for $CONCURRENT requests"
echo "=== Load Test: $PASS/$CONCURRENT passed ==="
[ "$FAIL" -eq 0 ] && echo "LOAD TEST OK" || echo "LOAD TEST FAILED"
exit $FAIL
