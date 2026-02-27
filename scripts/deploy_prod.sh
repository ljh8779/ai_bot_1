#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not installed." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env.prod not found. Run:" >&2
  echo "  cp .env.prod.example .env.prod" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

if [[ -z "${BULK_INGEST_HOST_DIR:-}" ]]; then
  echo "BULK_INGEST_HOST_DIR is not set in .env.prod" >&2
  exit 1
fi

mkdir -p "${BULK_INGEST_HOST_DIR}"

docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" pull
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up --build -d
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps

echo ""
echo "Health check:"
curl -fsS "http://localhost/health" || {
  echo "Health check failed via http://localhost/health" >&2
  exit 1
}
echo ""
echo "Deployment complete."

