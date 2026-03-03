#!/usr/bin/env bash
set -euo pipefail

# Run production stack in HTTP-only mode (no TLS on 443).
# Useful when certificate issuance fails and you need temporary access.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.prod" ]]; then
  echo ".env.prod not found. Create it first (cp .env.prod.example .env.prod)." >&2
  exit 1
fi

cat > docker-compose.prod.http.override.yml <<'EOF'
services:
  caddy:
    ports:
      - "80:80"
    volumes:
      - ./deploy/caddy/Caddyfile.http:/etc/caddy/Caddyfile:ro
EOF

echo "[1/4] Build and start api+caddy (HTTP only)..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.http.override.yml \
  --env-file .env.prod \
  up -d --build api caddy

echo "[2/4] Container status..."
sudo docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.http.override.yml \
  --env-file .env.prod \
  ps

set -a
source .env.prod
set +a

echo "[3/4] Route health check (HTTP)..."
curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health"
echo ""

echo "[4/4] Done."
echo "Open: http://${DOMAIN}"
