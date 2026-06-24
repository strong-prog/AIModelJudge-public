#!/usr/bin/env bash
# локальный аудит зависимостей + генерация SBOM
# Использование: bash scripts/audit-deps.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Dependency Vulnerability Scan (pip-audit) ==="
pip install -q pip-audit 2>/dev/null
pip-audit --requirement pyproject.toml

echo ""
echo "=== SBOM Generation (cyclonedx-py) ==="
pip install -q cyclonedx-py 2>/dev/null
SBOM_FILE="sbom-$(date +%Y%m%d-%H%M%S).json"
cyclonedx-py requirements pyproject.toml -o "$SBOM_FILE"
echo "SBOM saved to $SBOM_FILE"

echo ""
echo "=== Installed vs Declared Dependencies ==="
pip install -q pipdeptree 2>/dev/null && pipdeptree --warn silence || true

echo ""
echo "Audit complete."
