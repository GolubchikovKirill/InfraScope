#!/usr/bin/env bash
# Local development stack in Docker (docker-compose.local.yml) - the Linux/macOS
# twin of scripts/dev-up.ps1 (bash 3.2 as shipped with macOS is enough). Usage: ./scripts/dev-up.sh [--from-prod-backup|--logs|--down|--reset]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE=(docker compose -p infrascope-local -f docker-compose.yml -f docker-compose.local.yml)
SERVICES=(db redis backend worker beat frontend-dev)

docker info >/dev/null 2>&1 || { echo "Docker is not running." >&2; exit 1; }

case "${1:-}" in
  --down) "${COMPOSE[@]}" down; exit 0 ;;
  --reset) "${COMPOSE[@]}" down -v; echo "Local stack stopped, local volumes removed."; exit 0 ;;
  --logs) exec "${COMPOSE[@]}" logs -f --tail 100 backend worker ;;
esac

# URL-safe base64 of N random bytes (for 32 bytes that is exactly a Fernet key).
# openssl ships with macOS; python3 there may be only the Xcode-install stub.
secret() { openssl rand -base64 "$1" | tr -d '\n' | tr '+/' '-_'; }

if [ -f .env ]; then
  if grep -Eq "^[[:space:]]*ENVIRONMENT[[:space:]]*=[[:space:]]*['\"]?production" .env; then
    echo ".env here is a production one (ENVIRONMENT=production) and carries live integration tokens." >&2
    echo "Move it away (mv .env .env.prod-copy) and run this again." >&2
    exit 1
  fi
  echo "Using the existing .env (ENVIRONMENT is forced to development by docker-compose.local.yml)."
else
  sed -e "s|^SECRET_KEY=__GENERATED__|SECRET_KEY=$(secret 48)|" \
      -e "s|^CREDENTIALS_ENCRYPTION_KEYS=__GENERATED__|CREDENTIALS_ENCRYPTION_KEYS=$(secret 32)|" \
      .env.local.example > .env
  echo "Created .env from .env.local.example with fresh keys."
fi

"${COMPOSE[@]}" up -d --build "${SERVICES[@]}"

echo "Waiting for the API (migrations run on first start)..."
for _ in $(seq 1 80); do
  curl -fsS -m 3 http://localhost:8000/health >/dev/null 2>&1 && break
  sleep 3
done
curl -fsS -m 3 http://localhost:8000/health >/dev/null 2>&1 || {
  "${COMPOSE[@]}" logs --tail 60 backend; echo "The API did not come up; its log is above." >&2; exit 1; }

if [ "${1:-}" = "--from-prod-backup" ]; then
  latest="$(ssh infrascope-server 'ls -1t ~/InfraScope/backups/postgres/daily/*.dump | head -n 1')"
  [ -n "$latest" ] || { echo "No backup found on the server." >&2; exit 1; }
  mkdir -p backups/local
  scp "infrascope-server:$latest" backups/local/prod-latest.dump
  "${COMPOSE[@]}" stop backend worker beat
  "${COMPOSE[@]}" cp backups/local/prod-latest.dump db:/tmp/prod.dump
  "${COMPOSE[@]}" exec -T db sh -c "pg_restore -U postgres -d infrascope -c --if-exists --no-owner /tmp/prod.dump; rm -f /tmp/prod.dump"
  "${COMPOSE[@]}" start backend worker beat
  echo "Restored $latest. Encrypted passwords stay unreadable here, by design; log in with your prod login."
fi

email="$(grep -E '^FIRST_SUPERUSER_EMAIL=' .env | cut -d= -f2-)"
password="$(grep -E '^FIRST_SUPERUSER_PASSWORD=' .env | cut -d= -f2-)"
cat <<MSG

Local InfraScope is up:
  App   http://localhost:5173   (hot reload)
  API   http://localhost:8000/docs
  Login ${email} / ${password}
Hardware writes are OFF: no AP reboots, no DHCP cleanup, no switch writes from this stack.
MSG
