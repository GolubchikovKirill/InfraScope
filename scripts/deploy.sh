#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

USE_PROD_NETWORK=0
SKIP_GIT_PULL=0
BUILD_LOCAL=0

for arg in "$@"; do
  case "$arg" in
    --prod-network) USE_PROD_NETWORK=1 ;;
    --no-pull) SKIP_GIT_PULL=1 ;;
    --build-local) BUILD_LOCAL=1 ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: ./scripts/deploy.sh [--prod-network] [--no-pull] [--build-local]"
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required"
  exit 1
fi
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is required"
  exit 1
}

if [ ! -f ".env" ]; then
  echo ".env not found. Copy .env.example -> .env and fill secrets first."
  exit 1
fi

if [ "$SKIP_GIT_PULL" -eq 0 ]; then
  git pull --ff-only
fi

COMPOSE_FILES=(-f docker-compose.yml)
if [ "$USE_PROD_NETWORK" -eq 1 ]; then
  COMPOSE_FILES+=(-f docker-compose.prod.yml)
fi

echo "Starting deployment..."
if [ "$BUILD_LOCAL" -eq 1 ]; then
  echo "Local image build mode is enabled."
  docker compose "${COMPOSE_FILES[@]}" up -d --build
else
  echo "Immutable deploy mode: using prebuilt images."
  docker compose "${COMPOSE_FILES[@]}" up -d
fi

check_health() {
  local service="$1"
  local status
  status="$(docker compose "${COMPOSE_FILES[@]}" ps --format json "$service" | python3 -c 'import json,sys; data=[json.loads(x) for x in sys.stdin if x.strip()]; print(data[0].get("Health","") if data else "")')"
  if [ -z "$status" ] || [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
    return 0
  fi
  return 1
}

DEPLOY_SERVICES="$(python3 tools/scaffold/list_deploy_services.py)"

for service in $DEPLOY_SERVICES; do
  for _ in $(seq 1 30); do
    if check_health "$service"; then
      break
    fi
    sleep 2
  done
  if ! check_health "$service"; then
    echo "Service '$service' is not healthy"
    docker compose "${COMPOSE_FILES[@]}" ps
    exit 1
  fi
done

echo "Deployment complete."
echo "Health endpoint:"
curl -kfsS "https://localhost/ready" >/dev/null 2>&1 && echo "  frontend proxy readiness: ok" || echo "  frontend proxy readiness: unreachable"
