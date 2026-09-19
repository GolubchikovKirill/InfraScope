#!/usr/bin/env bash
set -euo pipefail

# Nightly PostgreSQL backup with local rotation. Meant to run from cron,
# unattended, against the compose stack in this directory.
#
# Usage:
#   ./scripts/backup-postgres.sh
#
# Cron example (01:00 UTC - after the 15-min device poll noise settles and
# well before the 02:00 UTC ML retrain and the 04:30/16:30 UTC AP-reboot
# windows documented in CLAUDE.md):
#   0 1 * * * cd /path/to/InfraScope && ./scripts/backup-postgres.sh >> backups/postgres/cron.log 2>&1
#
# What this does NOT do, on purpose:
#   - Copy the backup off this host. Set BACKUP_REMOTE_COPY_CMD (see below)
#     to plug in whatever off-site target you actually have (another host,
#     object storage, ...) - this script has no opinion on which.
#   - Back up .env / the CREDENTIALS_ENCRYPTION_KEYS secret. A database dump
#     alone is undecryptable without that key, but .env also holds every
#     other production secret (DB password, SECRET_KEY, RUSTDESK_API token,
#     ...); bundling it into an automated, possibly-off-site backup turns
#     one more system into something that must itself be secured. Copy it
#     out manually, to a secret manager or equally access-controlled
#     location - not into this rotation.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is not available." >&2
  exit 1
fi

BACKUP_ROOT="${BACKUP_ROOT:-backups/postgres}"
DAILY_DIR="${BACKUP_ROOT}/daily"
WEEKLY_DIR="${BACKUP_ROOT}/weekly"
KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
# Optional hook: set to a command that takes the dump path as $1 to copy it
# off this host, e.g. BACKUP_REMOTE_COPY_CMD='rclone copy'.
BACKUP_REMOTE_COPY_CMD="${BACKUP_REMOTE_COPY_CMD:-}"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"
chmod 700 "$BACKUP_ROOT" "$DAILY_DIR" "$WEEKLY_DIR" 2>/dev/null || true

db_container="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" ps -q db 2>/dev/null || true)"
if [ -z "$db_container" ]; then
  echo "$(date -u +%FT%TZ) ERROR: no running db container, backup skipped." >&2
  exit 1
fi

db_user="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db printenv POSTGRES_USER 2>/dev/null || true)"
db_name="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db printenv POSTGRES_DB 2>/dev/null || true)"
db_user="${db_user:-postgres}"
db_name="${db_name:-infrascope}"

stamp="$(date -u +%Y%m%d-%H%M%S)"
dump_path="${DAILY_DIR}/postgres-${stamp}.dump"
tmp_path="${dump_path}.partial"

echo "$(date -u +%FT%TZ) Starting backup of database '${db_name}' -> ${dump_path}"

# Custom format (-Fc): compressed, supports selective/parallel restore via
# pg_restore, unlike the plain-SQL dump the deploy script's own
# pre-reset-volumes backup uses (that one is a last-resort safety net taken
# right before a destructive op, not a rotation - no need for the two to
# agree on format). Written to a .partial path first and renamed only on
# success, so a crashed or killed dump never leaves a truncated file that
# looks like a valid backup to the retention/prune logic below.
if "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" exec -T db \
    pg_dump -U "$db_user" -d "$db_name" -Fc > "$tmp_path"; then
  mv "$tmp_path" "$dump_path"
else
  echo "$(date -u +%FT%TZ) ERROR: pg_dump failed." >&2
  rm -f "$tmp_path"
  exit 1
fi

size_bytes="$(wc -c < "$dump_path" | tr -d '[:space:]')"
if [ "${size_bytes:-0}" -lt 1024 ]; then
  echo "$(date -u +%FT%TZ) ERROR: backup file suspiciously small (${size_bytes} bytes), treating as failed." >&2
  mv "$dump_path" "${dump_path}.suspect"
  exit 1
fi
echo "$(date -u +%FT%TZ) Backup written: ${dump_path} (${size_bytes} bytes)"

# ISO week boundary: keep the first successful backup of each week as the
# weekly copy, so weekly retention doesn't depend on cron firing at exactly
# the same moment every Sunday.
week_marker="${WEEKLY_DIR}/.last-week"
current_week="$(date -u +%G-W%V)"
last_week="$(cat "$week_marker" 2>/dev/null || true)"
if [ "$current_week" != "$last_week" ]; then
  cp "$dump_path" "${WEEKLY_DIR}/postgres-${stamp}.dump"
  printf '%s' "$current_week" > "$week_marker"
  echo "$(date -u +%FT%TZ) Weekly copy kept: ${WEEKLY_DIR}/postgres-${stamp}.dump"
fi

if [ -n "$BACKUP_REMOTE_COPY_CMD" ]; then
  if $BACKUP_REMOTE_COPY_CMD "$dump_path"; then
    echo "$(date -u +%FT%TZ) Off-site copy ok via: ${BACKUP_REMOTE_COPY_CMD}"
  else
    echo "$(date -u +%FT%TZ) WARNING: off-site copy failed (backup itself still succeeded locally)." >&2
  fi
fi

prune_dir() {
  local dir="$1"
  local keep="$2"
  # shellcheck disable=SC2012
  ls -1t "${dir}"/postgres-*.dump 2>/dev/null | tail -n "+$((keep + 1))" | while IFS= read -r stale; do
    rm -f "$stale"
    echo "$(date -u +%FT%TZ) Pruned old backup: ${stale}"
  done
}

prune_dir "$DAILY_DIR" "$KEEP_DAILY"
prune_dir "$WEEKLY_DIR" "$KEEP_WEEKLY"

date -u +%FT%TZ > "${BACKUP_ROOT}/.last_success"

# Exposed to Prometheus through node-exporter's textfile collector (the
# node-exporter service in docker-compose.yml mounts this directory), so the
# PostgresBackupStale alert fires when backups stop - a backup that silently
# stopped running is as dangerous as never having one. Written to a temp name
# and renamed: the collector must never read a half-written file. Kept
# world-readable because node-exporter runs as an unprivileged user.
METRICS_DIR="${BACKUP_METRICS_DIR:-backups/metrics}"
mkdir -p "$METRICS_DIR"
chmod 755 "$METRICS_DIR" 2>/dev/null || true
metrics_tmp="${METRICS_DIR}/.infrascope_backup.prom.$$"
{
  echo "# HELP infrascope_backup_last_success_timestamp_seconds Unix time of the last successful PostgreSQL backup."
  echo "# TYPE infrascope_backup_last_success_timestamp_seconds gauge"
  echo "infrascope_backup_last_success_timestamp_seconds $(date -u +%s)"
  echo "# HELP infrascope_backup_last_size_bytes Size of the last successful PostgreSQL backup."
  echo "# TYPE infrascope_backup_last_size_bytes gauge"
  echo "infrascope_backup_last_size_bytes ${size_bytes}"
} > "$metrics_tmp"
chmod 644 "$metrics_tmp"
mv "$metrics_tmp" "${METRICS_DIR}/infrascope_backup.prom"

echo "$(date -u +%FT%TZ) Backup cycle complete."
