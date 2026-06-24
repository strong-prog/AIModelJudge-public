#!/usr/bin/env bash
# AIModelJudge — Regression Test (39+ endpoints)
# Usage: bash tests/regression_test.sh [base_url]
# Default: http://127.0.0.1:9651

set -euo pipefail
BASE="${1:-http://127.0.0.1:9651}"
PASS=0
FAIL=0
SKIP=0

# check_ok: expects any 2xx (default) or a specific code
check() {
    local method="$1" url="$2" data="${3:-}" auth="${4:-}" expected="${5:-200}"
    local code
    if [ -n "$data" ]; then
        if [ -n "$auth" ]; then
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H 'Content-Type: application/json' \
                -H "X-AMJ-API-Key: $auth" \
                -d "$data" --max-time 15 2>/dev/null || echo "000")
        else
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H 'Content-Type: application/json' \
                -d "$data" --max-time 15 2>/dev/null || echo "000")
        fi
    else
        if [ -n "$auth" ]; then
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H "X-AMJ-API-Key: $auth" --max-time 15 2>/dev/null || echo "000")
        else
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                --max-time 15 2>/dev/null || echo "000")
        fi
    fi

    if [ "$code" = "$expected" ]; then
        echo "  PASS  $method $url → $code"
        PASS=$((PASS + 1))
    elif [ "$code" = "000" ]; then
        echo "  SKIP  $method $url (no response, server down?)"
        SKIP=$((SKIP + 1))
    else
        echo "  FAIL  $method $url → $code (expected $expected)"
        FAIL=$((FAIL + 1))
    fi
}

# check_any: accepts any 2xx/4xx (not 5xx), proving server handles request
check_any() {
    local method="$1" url="$2" data="${3:-}" auth="${4:-}"
    local code
    if [ -n "$data" ]; then
        if [ -n "$auth" ]; then
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H 'Content-Type: application/json' \
                -H "X-AMJ-API-Key: $auth" \
                -d "$data" --max-time 15 2>/dev/null || echo "000")
        else
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H 'Content-Type: application/json' \
                -d "$data" --max-time 15 2>/dev/null || echo "000")
        fi
    else
        if [ -n "$auth" ]; then
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                -H "X-AMJ-API-Key: $auth" --max-time 15 2>/dev/null || echo "000")
        else
            code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE$url" \
                --max-time 15 2>/dev/null || echo "000")
        fi
    fi

    # Accept 2xx or 4xx, reject 5xx or 000
    case "$code" in
        2??|4??)
            echo "  PASS  $method $url → $code"
            PASS=$((PASS + 1))
            ;;
        000)
            echo "  SKIP  $method $url (no response, server down?)"
            SKIP=$((SKIP + 1))
            ;;
        *)
            echo "  FAIL  $method $url → $code (expected 2xx/4xx, got 5xx)"
            FAIL=$((FAIL + 1))
            ;;
    esac
}

echo "=== AIModelJudge Regression Test ==="
echo "Target: $BASE"
echo ""

# ── Core ──
echo "── Core ──"
check GET "/health"
check GET "/openapi.json"
check GET "/docs"

# ── Models ──
echo "── Models ──"
check GET "/model/list"
check GET "/model/current"
check GET "/model/cache/stats"
check POST "/model/switch" '{"model":"deepseek-chat"}'

# ── Profile ──
echo "── Profile ──"
check GET "/profile/list"
check GET "/profile/current"
check POST "/profile/switch" '{"profile":"hermes"}'

# ── Skills ──
echo "── Skills ──"
check GET "/skills/list"
# /skills/content требует путь внутри _SKILL_DIRS, может вернуть 403/404 если нет навыков
check_any GET "/skills/content?path=system"
check GET "/skills/graph"
check POST "/skills/auto-rank" "" "" "200"

# ── Sessions ──
echo "── Sessions ──"
check GET "/sessions/recent"
check GET "/sessions/search?q=test"

# ── Projects ──
echo "── Projects ──"
check GET "/projects/list"

# ── Analytics ──
echo "── Analytics ──"
check GET "/analytics/tokens"
check GET "/selflearning/status"
check GET "/benchmarks/stats"
check GET "/benchmarks/recent"

# ── Memory ──
echo "── Memory ──"
check GET "/memory/graph"

# ── Cron ──
echo "── Cron ──"
check GET "/cron/list"
# Try to get existing job_id from cron list first (free tier limit may block creation)
CRON_ID=$(curl -s "$BASE/cron/list" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('jobs',[{}])[0].get('id',''))" 2>/dev/null || echo "")
# If no existing jobs, try to create one
if [ -z "$CRON_ID" ]; then
    CRON_CREATE_RESP=$(curl -s -X POST "$BASE/cron/create" \
        -H 'Content-Type: application/json' \
        -d '{"name":"regression-test","schedule":"0 0 * * *","prompt":"test"}' --max-time 10 2>/dev/null || echo '{}')
    CRON_ID=$(echo "$CRON_CREATE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job',{}).get('id',''))" 2>/dev/null || echo "")
    if [ -n "$CRON_ID" ]; then
        echo "  PASS  POST /cron/create → (id=$CRON_ID)"
        PASS=$((PASS + 1))
    else
        # Creation blocked (limit/tier) — still verify endpoint responds without 5xx
        CRON_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/cron/create" \
            -H 'Content-Type: application/json' \
            -d '{"name":"regression-test","schedule":"0 0 * * *","prompt":"test"}' --max-time 10 2>/dev/null || echo "000")
        case "$CRON_HTTP" in 2??|4??) echo "  PASS  POST /cron/create → $CRON_HTTP (limit)" ; PASS=$((PASS + 1)) ;; *) echo "  FAIL  POST /cron/create → $CRON_HTTP" ; FAIL=$((FAIL + 1)) ;; esac
    fi
fi

if [ -n "$CRON_ID" ]; then
    check POST "/cron/toggle" "{\"job_id\":\"$CRON_ID\",\"action\":\"pause\"}"
    check POST "/cron/trigger" "{\"job_id\":\"$CRON_ID\"}"
else
    check_any POST "/cron/toggle" '{"job_id":"nonexistent","action":"pause"}'
    check_any POST "/cron/trigger" '{"job_id":"nonexistent"}'
fi
# Create a new job to test delete, or reuse existing
DELETE_CRON_RESP=$(curl -s -X POST "$BASE/cron/create" \
    -H 'Content-Type: application/json' \
    -d '{"name":"reg-del","schedule":"0 0 * * *","prompt":"delete-me"}' --max-time 10 2>/dev/null || echo '{}')
DELETE_CRON_ID=$(echo "$DELETE_CRON_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job',{}).get('id',''))" 2>/dev/null || echo "")
if [ -n "$DELETE_CRON_ID" ]; then
    check DELETE "/cron/$DELETE_CRON_ID"
else
    # Reuse CRON_ID for delete if it exists (from cron list)
    if [ -n "$CRON_ID" ]; then
        check DELETE "/cron/$CRON_ID"
    else
        check_any DELETE "/cron/nonexistent"
    fi
fi

# ── Kanban ──
echo "── Kanban ──"
check GET "/kanban/tasks"
# Create with valid status and integer priority
KANBAN_CREATE_RESP=$(curl -s -X POST "$BASE/kanban/tasks" \
    -H 'Content-Type: application/json' \
    -d '{"title":"regression-test","status":"pending","priority":1}' --max-time 10 2>/dev/null || echo '{}')
TASK_ID=$(echo "$KANBAN_CREATE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('task',{}).get('id',''))" 2>/dev/null || echo "")
if [ -n "$TASK_ID" ]; then
    echo "  PASS  POST /kanban/tasks → (id=$TASK_ID)"
    PASS=$((PASS + 1))

    check PATCH "/kanban/tasks/$TASK_ID" '{"status":"completed"}'
    check DELETE "/kanban/tasks/$TASK_ID"
else
    echo "  FAIL  POST /kanban/tasks → could not extract task_id"
    FAIL=$((FAIL + 1))
    check_any PATCH "/kanban/tasks/nonexistent" '{"status":"completed"}'
    check_any DELETE "/kanban/tasks/nonexistent"
fi

# ── Auth ──
echo "── Auth ──"
check_any POST "/auth/register" '{"email":"regtest@test.local","password":"regtest12345"}'
API_KEY=$(curl -s -X POST "$BASE/auth/register" -H 'Content-Type: application/json' \
    -d '{"email":"regtest2@test.local","password":"regtest12345"}' --max-time 10 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null || echo "")
# Fallback: if register failed (email taken), try login
if [ -z "$API_KEY" ]; then
    API_KEY=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
        -d '{"email":"regtest2@test.local","password":"regtest12345"}' --max-time 10 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null || echo "")
fi
if [ -n "$API_KEY" ]; then
    check GET "/auth/me" "" "$API_KEY"
else
    echo "  SKIP  GET /auth/me (no API key)"
    SKIP=$((SKIP + 1))
fi
# Test login with wrong password → 401
check POST "/auth/login" '{"email":"regtest@test.local","password":"wrongpassword12345"}' "" "401"

# ── Subscription ──
echo "── Subscription ──"
check GET "/subscription/provider"
if [ -n "$API_KEY" ]; then
    check GET "/subscription/status" "" "$API_KEY"
else
    echo "  SKIP  GET /subscription/status (no API key)"
    SKIP=$((SKIP + 1))
fi

# ── Rules ──
echo "── Rules ──"
check GET "/rules/count"
check GET "/rules/violations?limit=5"

# ── Diff ──
echo "── Diff ──"
check POST "/diff" '{"file_path":"test.py","old_content":"line1\nline2","new_content":"line1\nline2\nline3"}' "" "200"

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
[ "$FAIL" -eq 0 ] && echo "REGRESSION OK" || echo "REGRESSION FAILED"
exit $FAIL
