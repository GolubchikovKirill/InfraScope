#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/5] Backend lint (ruff)..."
uv run ruff check app tests scripts

echo "[2/5] Backend tests (pytest)..."
uv run pytest tests

echo "[3/5] Frontend install..."
cd frontend
npm ci

echo "[4/5] Frontend typecheck..."
npm run typecheck

echo "[5/5] Frontend tests..."
npm run test:run

echo "Quality gate passed."
