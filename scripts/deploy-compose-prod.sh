#!/usr/bin/env bash
set -euo pipefail

# Production deploy wrapper (Compose only).
#
# Default mode:
#   - validates compose config
#   - pulls git changes
#   - builds app images with retries
#   - starts/recreates the full stack without removing volumes
#
# Safe clean mode:
#   ./scripts/deploy-compose-prod.sh --clean
#   - stops/removes containers and networks
#   - keeps all volumes, including PostgreSQL data
#   - starts the full stack from scratch
#
# Destructive reset mode:
#   CONFIRM_RESET_VOLUMES=YES ./scripts/deploy-compose-prod.sh --reset-volumes
#   - attempts a PostgreSQL backup first
#   - removes compose volumes
#   - starts from empty data

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

unset DOCKER_HOST || true
unset COMPOSE_FILE || true

MODE="deploy"
SKIP_GIT_PULL=0
SKIP_BACKUP=0

for arg in "$@"; do
  case "$arg" in
    --clean) MODE="clean" ;;
    --reset-volumes) MODE="reset-volumes" ;;
    --no-pull) SKIP_GIT_PULL=1 ;;
    --skip-backup) SKIP_BACKUP=1 ;;
    -h|--help)
      sed -n '1,28p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--clean|--reset-volumes] [--no-pull] [--skip-backup]"
      exit 1
      ;;
  esac
done

APP_SERVICES=(
  backend
  worker
  frontend
  polling-service
  discovery-service
  network-control-service
  ml-service
  media-service
)

BUILD_RETRIES="${BUILD_RETRIES:-3}"
BUILD_RETRY_DELAY_SECONDS="${BUILD_RETRY_DELAY_SECONDS:-10}"
PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
PIP_RETRIES="${PIP_RETRIES:-10}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
FORCE_NO_CACHE="${FORCE_NO_CACHE:-0}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

if [ ! -f ".env" ]; then
  echo ".env not found. Copy .env.example -> .env first."
  exit 1
fi

if ! grep -q '^COMPOSE_PROJECT_NAME=' .env; then
  echo "COMPOSE_PROJECT_NAME=infrascope" >> .env
fi

env_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"
  line="${line#\"}"
  line="${line%\'}"
  line="${line#\'}"
  printf '%s' "$line"
}

is_placeholder() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  [ -z "$value" ] || [ "$value" = "changethis" ] || [ "$value" = "change_me" ] || [ "$value" = "change-me" ] || [ "$value" = "changeme" ]
}

validate_production_env() {
  local environment
  local secret_key
  local postgres_password
  local first_password
  local internal_token
  local internal_services_enabled
  local errors

  environment="$(env_value ENVIRONMENT)"
  [ "${environment:-development}" = "production" ] || return 0

  secret_key="$(env_value SECRET_KEY)"
  postgres_password="$(env_value POSTGRES_PASSWORD)"
  first_password="$(env_value FIRST_SUPERUSER_PASSWORD)"
  internal_token="$(env_value INTERNAL_SERVICE_TOKEN)"
  internal_services_enabled=0
  for flag in POLLING_SERVICE_ENABLED DISCOVERY_SERVICE_ENABLED NETWORK_CONTROL_SERVICE_ENABLED MEDIA_SERVICE_ENABLED; do
    case "$(printf '%s' "$(env_value "$flag")" | tr '[:upper:]' '[:lower:]')" in
      true|1|yes|on) internal_services_enabled=1 ;;
    esac
  done

  errors=0
  if is_placeholder "$secret_key" || [ "${#secret_key}" -lt 32 ]; then
    echo ".env: SECRET_KEY must be a generated production secret (32+ chars)."
    errors=1
  fi
  if is_placeholder "$postgres_password" || [ "${#postgres_password}" -lt 12 ]; then
    echo ".env: POSTGRES_PASSWORD is weak. Keep it only if this existing PostgreSQL volume was initialized with that password."
    echo "      To rotate it safely, change the DB role password inside PostgreSQL first, then update .env."
  fi
  if is_placeholder "$first_password" || [ "${#first_password}" -lt 12 ]; then
    echo ".env: FIRST_SUPERUSER_PASSWORD must be set to a strong value (12+ chars)."
    errors=1
  fi
  if [ "$internal_services_enabled" -eq 1 ] && { is_placeholder "$internal_token" || [ "${#internal_token}" -lt 24 ]; }; then
    echo ".env: INTERNAL_SERVICE_TOKEN must be set when internal services are enabled."
    errors=1
  fi

  if [ "$errors" -ne 0 ]; then
    cat <<'EOF'

Generate safe values on the server, for example:
  python3 - <<'PY'
import secrets
for key in ("SECRET_KEY", "POSTGRES_PASSWORD", "FIRST_SUPERUSER_PASSWORD", "INTERNAL_SERVICE_TOKEN", "MEDIA_CLIENT_TOKEN"):
    print(f"{key}={secrets.token_urlsafe(32)}")
PY

Update .env and run the deploy script again.
EOF
    exit 1
  fi
}

validate_production_env

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is not available. Install docker compose plugin or docker-compose."
  exit 1
fi

docker info >/dev/null 2>&1 || {
  echo "Docker daemon is not available. Start docker and retry."
  exit 1
}

echo "[1/7] Validate compose config..."
"${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" config -q

if [ "$SKIP_GIT_PULL" -eq 0 ]; then
  echo "[2/7] Pull latest changes..."
  git pull --ff-only
else
  echo "[2/7] Git pull skipped."
fi

backup_db() {
  local backup_dir="backups"
  local stamp
  local db_user
  local db_name
  local db_container

  mkdir -p "$backup_dir"
  stamp="$(date +%Y%m%d-%H%M%S)"
  db_container="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" ps -q db 2>/dev/null || true)"
  if [ -z "$db_container" ]; then
    echo "No running db container found, backup skipped."
    return 0
  fi
  db_user="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db printenv POSTGRES_USER 2>/dev/null || true)"
  db_name="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db printenv POSTGRES_DB 2>/dev/null || true)"
  db_user="${db_user:-postgres}"
  db_name="${db_name:-infrascope}"

  echo "Creating PostgreSQL backup: ${backup_dir}/postgres-${stamp}.sql"
  if "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db pg_dump -U "$db_user" -d "$db_name" > "${backup_dir}/postgres-${stamp}.sql"; then
    gzip -f "${backup_dir}/postgres-${stamp}.sql"
    echo "Backup ready: ${backup_dir}/postgres-${stamp}.sql.gz"
  else
    echo "PostgreSQL backup failed."
    return 1
  fi
}

if [ "$MODE" = "reset-volumes" ]; then
  if [ "${CONFIRM_RESET_VOLUMES:-}" != "YES" ]; then
    echo "Refusing to remove volumes without confirmation."
    echo "Run: CONFIRM_RESET_VOLUMES=YES $0 --reset-volumes"
    exit 1
  fi
  if [ "$SKIP_BACKUP" -ne 1 ]; then
    backup_db || {
      echo "Reset stopped because backup failed. Use --skip-backup only if data loss is acceptable."
      exit 1
    }
  fi
fi

if [ "$MODE" = "clean" ]; then
  echo "[3/7] Clean restart requested: removing containers and networks, keeping volumes..."
  "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" down --remove-orphans
elif [ "$MODE" = "reset-volumes" ]; then
  echo "[3/7] Destructive reset requested: removing containers, networks, and volumes..."
  "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" down --remove-orphans -v
else
  echo "[3/7] Keeping existing containers/volumes."
fi

echo "[4/7] Build app images..."
build_ok=0
for attempt in $(seq 1 "$BUILD_RETRIES"); do
  echo "Build attempt ${attempt}/${BUILD_RETRIES}..."
  build_args=()
  if [ "$FORCE_NO_CACHE" = "1" ]; then
    build_args+=(--no-cache)
  fi
  if DOCKER_BUILDKIT=1 "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" build "${build_args[@]}" \
    --build-arg PIP_DEFAULT_TIMEOUT="$PIP_DEFAULT_TIMEOUT" \
    --build-arg PIP_RETRIES="$PIP_RETRIES" \
    --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" \
    "${APP_SERVICES[@]}"; then
    build_ok=1
    break
  fi
  if [ "$attempt" -lt "$BUILD_RETRIES" ]; then
    echo "Build failed, retrying in ${BUILD_RETRY_DELAY_SECONDS}s..."
    sleep "$BUILD_RETRY_DELAY_SECONDS"
  fi
done

if [ "$build_ok" -ne 1 ]; then
  echo "Build failed after ${BUILD_RETRIES} attempts."
  exit 1
fi

echo "[5/7] Start full stack..."
"${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" up -d --remove-orphans

echo "[6/7] Container status..."
"${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" ps

echo "[7/7] Readiness check..."
for _ in $(seq 1 30); do
  if curl -kfsS https://localhost/ready >/dev/null 2>&1; then
    echo "readiness: ok"
    exit 0
  fi
  sleep 2
done

echo "readiness: failed"
"${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" logs backend | tail -n 120 || true
exit 1
