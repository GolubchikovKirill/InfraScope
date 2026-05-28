#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$ROOT_DIR/.git/hooks"
PRE_PUSH_HOOK="$HOOKS_DIR/pre-push"

mkdir -p "$HOOKS_DIR"

cat >"$PRE_PUSH_HOOK" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

echo "Running pre-push quality gate..."
./scripts/quality-gate.sh
EOF

chmod +x "$PRE_PUSH_HOOK"
echo "Installed pre-push hook: $PRE_PUSH_HOOK"
