#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running smoke + contract checks..."
uv run python tools/scaffold/validate_service_descriptors.py
uv run pytest tests/integration/api/test_observability.py tests/integration/api/test_tasks.py tests/integration/api/test_boarding_pass.py tests/integration/api/test_qr_generator.py tests/integration/api/test_onec_exchange.py tests/unit/services/test_boarding_pass_service.py tests/unit/services/test_qr_generator_service.py tests/unit/architecture/test_layer_boundaries.py -q
cd frontend
npm run test:run -- src/App.test.tsx src/components/BoardingPassPanel.test.tsx
cd ..

if [[ -n "${SMOKE_BASE_URL:-}" && -n "${SMOKE_ADMIN_EMAIL:-}" && -n "${SMOKE_ADMIN_PASSWORD:-}" ]]; then
  uv run python scripts/smoke_boarding_pass.py
else
  echo "Skipping live boarding pass smoke. Set SMOKE_BASE_URL, SMOKE_ADMIN_EMAIL, and SMOKE_ADMIN_PASSWORD to enable it."
fi

echo "Smoke + contract checks passed."
