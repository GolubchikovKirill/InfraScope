#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FORWARDED_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --prod-network)
      echo "Warning: --prod-network is deprecated and ignored. Production deploy uses compose overrides by default."
      ;;
    --build-local)
      echo "Warning: --build-local is deprecated and ignored. deploy-compose-prod.sh always builds app images."
      ;;
    --no-pull|--clean|--reset-volumes|--skip-backup)
      FORWARDED_ARGS+=("$arg")
      ;;
    -h|--help)
      exec ./scripts/deploy-compose-prod.sh --help
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: ./scripts/deploy.sh [--clean] [--reset-volumes] [--no-pull] [--skip-backup]"
      exit 1
      ;;
  esac
done

exec ./scripts/deploy-compose-prod.sh "${FORWARDED_ARGS[@]}"
