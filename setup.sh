#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        InfraScope — Setup            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 1. Check Docker ──────────────────────────────────────────

command -v docker >/dev/null 2>&1 || error "Docker не установлен. Установите: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 не найден."
info "Docker найден: $(docker --version | head -1)"

# ── 2. Create .env ───────────────────────────────────────────

if [ ! -f .env ]; then
    cp .env.example .env

    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
          || openssl rand -base64 32 | tr -d '/+=' | head -c 43)
    DB_PASS=$(openssl rand -base64 16 | tr -d '/+=' | head -c 20)
    ADMIN_PASS="Admin$(openssl rand -base64 6 | tr -d '/+=' | head -c 8)1!"

    sed -i.bak "s|SECRET_KEY=CHANGE_ME|SECRET_KEY=${SECRET}|" .env
    sed -i.bak "s|POSTGRES_PASSWORD=CHANGE_ME|POSTGRES_PASSWORD=${DB_PASS}|" .env
    sed -i.bak "s|FIRST_SUPERUSER_PASSWORD=CHANGE_ME|FIRST_SUPERUSER_PASSWORD=${ADMIN_PASS}|" .env
    rm -f .env.bak

    info "Файл .env создан"
    info "Пароль администратора: ${ADMIN_PASS}"
    warn "Сохраните этот пароль! Он больше не будет показан."
else
    info "Файл .env уже существует — пропускаю"
fi

# ── 3. SSL certificates (mkcert or self-signed in Docker) ────

if command -v mkcert >/dev/null 2>&1; then
    if [ ! -f certs/cert.pem ] || [ ! -f certs/key.pem ]; then
        mkdir -p certs
        mkcert -install 2>/dev/null || warn "mkcert -install требует sudo. Запустите вручную: sudo mkcert -install"
        mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
            infrascope.local localhost 127.0.0.1 ::1
        info "SSL-сертификаты созданы (mkcert — доверенные)"
    else
        info "SSL-сертификаты уже существуют"
    fi
else
    warn "mkcert не найден — будут использованы самоподписанные сертификаты"
    warn "Для доверенных сертификатов установите mkcert:"
    case "$(uname)" in
        Darwin) warn "  brew install mkcert && mkcert -install" ;;
        *)      warn "  sudo apt install mkcert && mkcert -install" ;;
    esac
fi

# ── 4. Local domain ─────────────────────────────────────────

if ! grep -q "infrascope.local" /etc/hosts 2>/dev/null; then
    echo ""
    warn "Домен infrascope.local не найден в /etc/hosts"
    warn "Выполните вручную:"
    warn "  sudo sh -c 'echo \"127.0.0.1 infrascope.local\" >> /etc/hosts'"
    echo ""
else
    info "Домен infrascope.local настроен"
fi

# ── 5. SCAN_SUBNET prompt ───────────────────────────────────

CURRENT_SUBNET=$(grep "^SCAN_SUBNET=" .env | cut -d= -f2-)
if [ -z "$CURRENT_SUBNET" ]; then
    echo ""
    echo -n "Подсети для сканирования принтеров (например 10.10.98.0/24, 10.10.99.0/24): "
    read -r SUBNET_INPUT
    if [ -n "$SUBNET_INPUT" ]; then
        sed -i.bak "s|^SCAN_SUBNET=.*|SCAN_SUBNET=${SUBNET_INPUT}|" .env
        rm -f .env.bak
        info "SCAN_SUBNET установлен: ${SUBNET_INPUT}"
    else
        warn "SCAN_SUBNET не задан — сканер сети будет недоступен до настройки в .env"
    fi
fi

# ── 6. Build and start ──────────────────────────────────────

echo ""
info "Сборка и запуск контейнеров..."
echo ""

if [ -d certs ] && [ -f certs/cert.pem ]; then
    docker compose -f docker-compose.yml up -d --build \
        -e CERTS_VOLUME="./certs:/etc/nginx/certs:ro" 2>/dev/null \
    || docker compose up -d --build
else
    docker compose up -d --build
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        InfraScope запущен!           ║"
echo "  ╠══════════════════════════════════════╣"
echo "  ║  https://infrascope.local            ║"
echo "  ║  https://localhost                   ║"
echo "  ║  API: https://localhost/docs         ║"
echo "  ╠══════════════════════════════════════╣"
echo "  ║  Логин: admin@infrascope.dev         ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
