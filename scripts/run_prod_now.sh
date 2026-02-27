#!/usr/bin/env bash
set -euo pipefail

# Quick production runner for EC2
# - creates override to force uvicorn workers=1 (avoids startup race)
# - rebuilds/restarts services
# - checks health through local reverse proxy route

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
EOF

echo "[1/4] Building and starting services..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.override.yml \
  --env-file .env.prod \
  up -d --build

echo "[2/4] Container status..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.override.yml \
  --env-file .env.prod \
  ps

set -a
source .env.prod
set +a

echo "[3/4] Health check..."
curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health"
echo ""

echo "[4/4] Done."
echo "Open: https://${DOMAIN}"
