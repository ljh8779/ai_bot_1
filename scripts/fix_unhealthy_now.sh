#!/usr/bin/env bash
set -euo pipefail

# Emergency recovery runner when api container is unhealthy.
# - forces uvicorn workers=1
# - changes healthcheck target to /docs (liveness-level)
# - rebuilds/restarts stack
# - prints status and logs tail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.prod" ]]; then
  echo ".env.prod not found. Create it first (cp .env.prod.example .env.prod)." >&2
  exit 1
fi

cat > docker-compose.prod.override.yml <<'EOF'
services:
  api:
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')\""]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s
EOF

echo "[1/4] Rebuild and restart..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.override.yml \
  --env-file .env.prod \
  up -d --build

echo "[2/4] Compose status..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.override.yml \
  --env-file .env.prod \
  ps

set -a
source .env.prod
set +a

echo "[3/4] Route health check..."
curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health" || true
echo ""

echo "[4/4] Recent api logs..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.override.yml \
  --env-file .env.prod \
  logs --tail=80 api

echo ""
echo "Done. Open: https://${DOMAIN}"
