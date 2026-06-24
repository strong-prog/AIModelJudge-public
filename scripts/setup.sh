#!/usr/bin/env bash
# AIModelJudge — установка изолированного окружения
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[AIModelJudge]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="$HOME/.hermes-aimodeljudge"

log "Project: $PROJECT_DIR"
log "Hermes home: $HERMES_HOME"

# 1. Создать Hermes home
log "1/6 Создание $HERMES_HOME..."
mkdir -p "$HERMES_HOME"/{logs,skills,memories,state}

# 2. Конфиг
log "2/6 Копирование config.yaml..."
cp -f "$PROJECT_DIR/config/hermes/config.yaml" "$HERMES_HOME/config.yaml"
log "config.yaml установлен"

# 3. .env
log "3/6 Настройка .env..."
if [ ! -f "$HERMES_HOME/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$HERMES_HOME/.env"
    log ".env создан из примера — ЗАПОЛНИ КЛЮЧИ: nano $HERMES_HOME/.env"
else
    warn ".env уже существует — пропускаем"
fi

# 4. Копирование skills
log "4/6 Копирование skills..."
cp -rn "$PROJECT_DIR/config/hermes/skills/"* "$HERMES_HOME/skills/" 2>/dev/null || true
log "Skills скопированы"

# 5. Systemd units
log "5/6 Установка systemd-юнитов..."
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"
for unit in aimodeljudge-gateway aimodeljudge-router aimodeljudge-bridge aimodeljudge-cc-proxy aimodeljudge-web; do
    SRC="$PROJECT_DIR/config/hermes/systemd/${unit}.service"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$SYSTEMD_DIR/"
        log "  $unit.service установлен"
    else
        warn "  $unit.service не найден"
    fi
done
systemctl --user daemon-reload
log "systemd daemon-reload выполнен"

# 6. Linger
log "6/6 Включение linger..."
loginctl enable-linger "$(whoami)" 2>/dev/null || warn "loginctl не удался"

echo ""
echo "============================================"
echo -e "  ${GREEN}AIModelJudge — установка завершена!${NC}"
echo "============================================"
echo ""
echo "Дальнейшие шаги:"
echo "  1. Заполни ключи:  nano $HERMES_HOME/.env"
echo "  2. Запусти сервисы:"
echo "     systemctl --user enable --now aimodeljudge-gateway"
echo "     systemctl --user enable --now aimodeljudge-router"
echo "     systemctl --user enable --now aimodeljudge-bridge"
echo "     systemctl --user enable --now aimodeljudge-cc-proxy"
echo "     systemctl --user enable --now aimodeljudge-web"
echo "  3. Открой веб:      http://127.0.0.1:9651"
echo ""
echo "Порты:"
echo "  aimodeljudge-gateway   :9642  (Hermes Agent)"
echo "  aimodeljudge-router    :9084  (Smart Router)"
echo "  aimodeljudge-bridge    :9085  (Anthropic Bridge)"
echo "  aimodeljudge-cc-proxy  :9086  (CC Proxy)"
echo "  aimodeljudge-web       :9651  (Web Interface)"
echo ""
echo "Сравнение моделей из CLI:"
echo "  cd $PROJECT_DIR"
echo "  services/hermes-core/.venv/bin/python scripts/model_compare.py 'Your query'"
