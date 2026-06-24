#!/usr/bin/env bash
# AIModelJudge — Supply chain security check
# Usage: ./scripts/supply-chain-check.sh
# Checks: pip-audit (CVE), SBOM generation, SLSA verification

set -euo pipefail

echo "=== Supply Chain Security Check ==="
echo ""

# ── 1. pip-audit: CVE scan ──
echo "── pip-audit (CVE scan) ──"
if command -v pip-audit &>/dev/null; then
  pip-audit --requirement pyproject.toml || {
    echo "⚠  pip-audit found vulnerabilities — review before deploy"
  }
else
  echo "pip-audit not installed. Run: pip install pip-audit"
fi
echo ""

# ── 2. SBOM generation ──
echo "── SBOM (CycloneDX) ──"
if python3 -c "import cyclonedx_py" 2>/dev/null; then
  python3 -m cyclonedx_py -r -i pyproject.toml -o sbom.json
  echo "SBOM generated: sbom.json ($(wc -c < sbom.json) bytes)"
else
  echo "cyclonedx-py not installed. Run: pip install cyclonedx-py"
fi
echo ""

# ── 3. Check for known vulnerable packages ──
echo "── Known vulnerable package check ──"
if [ -f "pyproject.toml" ]; then
  # Quick check for packages with known issues in our version range
  grep -E '(pyjwt|jinja2|cryptography|aiofiles|pillow|websockets)' pyproject.toml | head -20
  echo "Verify each pinned version at: https://pypi.org/project/<name>/<version>/"
fi
echo ""

# ── 4. SLSA provenance ──
echo "── SLSA provenance ──"
if command -v slsa-verifier &>/dev/null; then
  slsa-verifier verify-artifact \
    --source-uri github.com/strong-prog/AIModelJudge \
    sbom.json 2>/dev/null || echo "⚠  SLSA verification failed or not configured"
else
  echo "slsa-verifier not installed. See: https://github.com/slsa-framework/slsa-verifier"
fi
echo ""

echo "=== Supply chain check complete ==="
