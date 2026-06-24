#!/bin/bash
# hermes-local-agent — однострочная установка
# curl -sSL https://raw.githubusercontent.com/strong-prog/AIModelJudge/main/services/hermes-local-agent/install.sh | bash

set -e

AGENT_DIR="$HOME/.hermes-agent"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== hermes-local-agent installer ==="

# Check Python
PYTHON=""
for py in python3 python3.12 python3.11 python3.10; do
    if command -v $py >/dev/null 2>&1; then
        PYTHON=$py
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ required but not found"
    exit 1
fi
echo "Python: $($PYTHON --version)"

# Install websockets dependency
$PYTHON -m pip install --user websockets 2>/dev/null || true

# Create directory and copy files
mkdir -p "$AGENT_DIR"
echo "Installing to $AGENT_DIR..."

# If we're running from the repo, copy from there
if [ -f "$REPO_DIR/install.sh" ] && [ "$REPO_DIR" != "$AGENT_DIR" ]; then
    cp "$REPO_DIR"/*.py "$AGENT_DIR/" 2>/dev/null || true
fi

# Create launcher script
cat > "$AGENT_DIR/run.sh" << 'LAUNCHER'
#!/bin/bash
cd "$HOME/.hermes-agent"
exec python3 main.py "$@"
LAUNCHER
chmod +x "$AGENT_DIR/run.sh"

# Create symlink
ln -sf "$AGENT_DIR/run.sh" "$HOME/.local/bin/hermes-local-agent" 2>/dev/null || true

# Interactive config
$PYTHON "$AGENT_DIR/main.py" --install

echo ""
echo "=== Готово ==="
echo "Запуск: hermes-local-agent"
echo "Или: cd ~/.hermes-agent && python3 main.py"
echo "Логи: ~/.hermes-agent/audit.jsonl"
echo "Конфиг: ~/.hermes-agent/config.json"
