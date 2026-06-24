#!/usr/bin/env bash
# автоматическая настройка TLS 1.3
# Запуск: sudo bash deploy/setup-tls.sh
# Требования: Ubuntu 22.04+ / Debian 12+, домен example.com направлен
set -euo pipefail

DOMAIN="${AMJ_DOMAIN:-example.com}"
EMAIL="${AMJ_ADMIN_EMAIL:-admin@example.com}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== TLS 1.3 Setup ==="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo ""

# ── 1. Установка nginx + certbot ──
echo "[1/6] Installing nginx + certbot..."
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

# ── 2. Копирование конфига nginx ──
echo "[2/6] Installing nginx config..."
cp "$REPO_DIR/deploy/nginx-aimodeljudge.conf" /etc/nginx/sites-available/aimodeljudge
ln -sf /etc/nginx/sites-available/aimodeljudge /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Создать директорию для ACME challenge
mkdir -p /var/www/certbot

# Проверить конфиг перед перезагрузкой
nginx -t

# ── 3. Перезагрузка nginx на HTTP ──
echo "[3/6] Starting nginx (HTTP only, for ACME)..."
systemctl reload nginx
systemctl enable nginx

# ── 4. Получение Let's Encrypt сертификата ──
echo "[4/6] Obtaining Let's Encrypt certificate..."
certbot certonly --webroot \
    -w /var/www/certbot \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive \
    --rsa-key-size 4096

# ── 5. Перезагрузка nginx с HTTPS ──
echo "[5/6] Reloading nginx with TLS 1.3..."
nginx -t && systemctl reload nginx

# ── 6. Автообновление сертификата ──
echo "[6/6] Setting up auto-renewal..."
CERTBOT_CRON="/etc/cron.d/certbot-aimodeljudge"
cat > "$CERTBOT_CRON" <<CRONEOF
# Auto-renew Let's Encrypt certificate for AIModelJudge
# Runs daily at 3:37am, reloads nginx on success
37 3 * * * root certbot renew --quiet --deploy-hook "systemctl reload nginx"
CRONEOF

echo ""
echo "=== TLS 1.3 Setup Complete ==="
echo ""
echo "Verification commands:"
echo "  curl -sI https://$DOMAIN/health | grep -i strict-transport"
echo "  openssl s_client -connect $DOMAIN:443 -tls1_3 </dev/null 2>&1 | grep -E 'Protocol|Cipher'"
echo "  nginx -T 2>&1 | grep ssl_protocols"
echo ""
echo "SSL Labs test: https://www.ssllabs.com/ssltest/analyze.html?d=$DOMAIN"
