#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"

read_env_value() {
  local file="$1"
  local key="$2"
  [[ -f "${file}" ]] || return 1
  grep -E "^${key}=" "${file}" | tail -n 1 | cut -d'=' -f2-
}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/restore_prod_db.sh /path/to/local.dump [/path/to/local.metadata.env]

Behavior:
  1. Validates production env and optional embedding dimensions metadata
  2. Backs up current production DB to backups/
  3. Stops api
  4. Restores the supplied dump into the production DB
  5. Starts api and prints post-restore stats
EOF
}

DUMP_FILE="${1:-}"
META_FILE="${2:-}"

if [[ -z "${DUMP_FILE}" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "Dump file not found: ${DUMP_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env.prod not found at ${ENV_FILE}" >&2
  exit 1
fi

POSTGRES_DB="$(read_env_value "${ENV_FILE}" POSTGRES_DB || true)"
POSTGRES_USER="$(read_env_value "${ENV_FILE}" POSTGRES_USER || true)"
POSTGRES_PASSWORD="$(read_env_value "${ENV_FILE}" POSTGRES_PASSWORD || true)"
DOMAIN="$(read_env_value "${ENV_FILE}" DOMAIN || true)"
EMBEDDING_DIMENSIONS="$(read_env_value "${ENV_FILE}" EMBEDDING_DIMENSIONS || true)"

if [[ -z "${POSTGRES_DB}" || -z "${POSTGRES_USER}" || -z "${POSTGRES_PASSWORD}" ]]; then
  echo "POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD must be set in .env.prod" >&2
  exit 1
fi

if [[ -n "${META_FILE}" ]]; then
  if [[ ! -f "${META_FILE}" ]]; then
    echo "Metadata file not found: ${META_FILE}" >&2
    exit 1
  fi
  EXPECTED_DIMS="$(read_env_value "${META_FILE}" EXPECTED_EMBEDDING_DIMENSIONS || true)"
  if [[ -n "${EXPECTED_DIMS}" && "${EMBEDDING_DIMENSIONS}" != "${EXPECTED_DIMS}" ]]; then
    echo "EMBEDDING_DIMENSIONS mismatch: prod=${EMBEDDING_DIMENSIONS} dump=${EXPECTED_DIMS}" >&2
    echo "Update .env.prod first, then rerun." >&2
    exit 1
  fi
fi

cd "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${ROOT_DIR}/backups/prod-before-local-${TIMESTAMP}.dump"

echo "[1/6] Backing up current production DB to ${BACKUP_FILE} ..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  db pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc > "${BACKUP_FILE}"

echo "[2/6] Stopping api ..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" stop api

echo "[3/6] Restoring ${DUMP_FILE} into production DB ..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  db pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" < "${DUMP_FILE}"

echo "[4/6] Starting api ..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d api

echo "[5/6] Post-restore DB stats ..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T \
  -e PGPASSWORD="${POSTGRES_PASSWORD}" \
  db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -F "|" -c \
  "select (select count(*) from documents), (select count(*) from document_chunks), (select format_type(atttypid, atttypmod) from pg_attribute where attrelid = 'document_chunks'::regclass and attname = 'embedding');"

echo "[6/6] Health check ..."
if [[ -n "${DOMAIN}" ]]; then
  curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health"
  echo ""
else
  echo "DOMAIN is empty in .env.prod. Skipping HTTP health check."
fi

echo ""
echo "Restore complete."
echo "Backup saved at: ${BACKUP_FILE}"
