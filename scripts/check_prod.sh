#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/.env.prod"

docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps
echo ""
echo "API health:"
curl -fsS "http://localhost/health"
echo ""
echo ""
echo "Recent logs (api):"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" logs --tail=80 api

