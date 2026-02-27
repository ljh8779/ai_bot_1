#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"

docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps
echo ""
echo "API health:"
set -a
source "${ENV_FILE}"
set +a
curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health"
echo ""
echo ""
echo "Recent logs (api):"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" logs --tail=80 api
