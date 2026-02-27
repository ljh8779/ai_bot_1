#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   REPO_URL="https://github.com/your/repo.git" \
#   ACME_EMAIL="ops@example.com" \
#   bash scripts/ec2_oneclick_setup.sh
#
# Optional:
#   DOMAIN="chat.example.com"                    # if omitted, auto -> <PUBLIC_IP>.nip.io
#   GOOGLE_API_KEY="xxxx"                        # if omitted, reuse from .env.prod/.env when possible
#   POSTGRES_PASSWORD="strong_password"          # if omitted, reuse from .env.prod/.env when possible
#   BULK_INGEST_HOST_DIR="/opt/ai_bot_folder"
#   AUTO_DOMAIN_NIP="1"                          # default: 1
#   USE_EXISTING_SECRETS="1"                     # default: 1

REPO_URL="${REPO_URL:-}"
APP_DIR="${APP_DIR:-$HOME/ai_bot_1}"
DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"
GOOGLE_API_KEY="${GOOGLE_API_KEY:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
BULK_INGEST_HOST_DIR="${BULK_INGEST_HOST_DIR:-/opt/ai_bot_folder}"
AUTO_DOMAIN_NIP="${AUTO_DOMAIN_NIP:-1}"
USE_EXISTING_SECRETS="${USE_EXISTING_SECRETS:-1}"
COMPOSE_VERSION="${COMPOSE_VERSION:-v2.27.0}"

read_env_value() {
  local file="$1"
  local key="$2"
  [[ -f "${file}" ]] || return 1
  grep -E "^${key}=" "${file}" | tail -n 1 | cut -d'=' -f2-
}

extract_password_from_database_url() {
  local database_url="$1"
  # postgresql+psycopg://user:password@host:port/db
  echo "${database_url}" | sed -E 's|^[^:]+://[^:]+:([^@]+)@.*$|\1|'
}

discover_public_ip() {
  local ip
  ip="$(curl -fsS http://checkip.amazonaws.com 2>/dev/null | tr -d '\n' || true)"
  if [[ -z "${ip}" ]]; then
    ip="$(curl -fsS https://ifconfig.me 2>/dev/null | tr -d '\n' || true)"
  fi
  echo "${ip}"
}

ensure_docker_compose() {
  if sudo docker compose version >/dev/null 2>&1; then
    return 0
  fi

  echo "docker compose plugin not found. Installing standalone plugin ${COMPOSE_VERSION}..."
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -fsSL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

  if ! sudo docker compose version >/dev/null 2>&1; then
    echo "Failed to install docker compose plugin." >&2
    exit 1
  fi
}

if [[ -z "${REPO_URL}" ]]; then
  echo "REPO_URL is required." >&2
  exit 1
fi
if [[ -z "${ACME_EMAIL}" ]]; then
  echo "ACME_EMAIL is required." >&2
  exit 1
fi

echo "[1/7] Installing Docker/Git..."
if command -v apt >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y docker.io git curl python3
  sudo apt install -y docker-compose-plugin || true
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf makecache -y
  sudo dnf install -y docker git python3
  sudo dnf install -y docker-compose-plugin || true
elif command -v yum >/dev/null 2>&1; then
  sudo yum makecache -y
  sudo yum install -y docker git python3
  sudo yum install -y docker-compose-plugin || true
else
  echo "No supported package manager found (apt/dnf/yum)." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  if command -v apt >/dev/null 2>&1; then
    sudo apt install -y curl
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y curl-minimal || sudo dnf install -y curl --allowerasing
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y curl-minimal || sudo yum install -y curl
  fi
fi

sudo systemctl enable --now docker
ensure_docker_compose

echo "[2/7] Cloning/Updating repository..."
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull --ff-only
else
  git clone "${REPO_URL}" "${APP_DIR}"
fi

cd "${APP_DIR}"

echo "[3/7] Preparing .env.prod..."
if [[ ! -f ".env.prod" ]]; then
  cp -f .env.prod.example .env.prod
fi

if [[ -z "${DOMAIN}" && "${AUTO_DOMAIN_NIP}" == "1" ]]; then
  PUB_IP="$(discover_public_ip)"
  if [[ -n "${PUB_IP}" ]]; then
    DOMAIN="${PUB_IP}.nip.io"
    echo "Auto domain selected: ${DOMAIN}"
  fi
fi

if [[ "${USE_EXISTING_SECRETS}" == "1" ]]; then
  if [[ -z "${GOOGLE_API_KEY}" ]]; then
    GOOGLE_API_KEY="$(read_env_value .env.prod GOOGLE_API_KEY || true)"
  fi
  if [[ -z "${GOOGLE_API_KEY}" ]]; then
    GOOGLE_API_KEY="$(read_env_value .env GOOGLE_API_KEY || true)"
  fi

  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    POSTGRES_PASSWORD="$(read_env_value .env.prod POSTGRES_PASSWORD || true)"
  fi
  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    POSTGRES_PASSWORD="$(read_env_value .env POSTGRES_PASSWORD || true)"
  fi
  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    DB_URL="$(read_env_value .env.prod DATABASE_URL || true)"
    if [[ -n "${DB_URL}" ]]; then
      POSTGRES_PASSWORD="$(extract_password_from_database_url "${DB_URL}")"
    fi
  fi
  if [[ -z "${POSTGRES_PASSWORD}" ]]; then
    DB_URL="$(read_env_value .env DATABASE_URL || true)"
    if [[ -n "${DB_URL}" ]]; then
      POSTGRES_PASSWORD="$(extract_password_from_database_url "${DB_URL}")"
    fi
  fi
fi

if [[ -z "${DOMAIN}" ]]; then
  echo "DOMAIN is required (or set AUTO_DOMAIN_NIP=1 with reachable public IP)." >&2
  exit 1
fi
if [[ -z "${GOOGLE_API_KEY}" ]]; then
  echo "GOOGLE_API_KEY is required (or provide existing .env/.env.prod)." >&2
  exit 1
fi
if [[ -z "${POSTGRES_PASSWORD}" ]]; then
  echo "POSTGRES_PASSWORD is required (or provide existing .env/.env.prod)." >&2
  exit 1
fi

export DOMAIN
export ACME_EMAIL
export GOOGLE_API_KEY
export POSTGRES_PASSWORD
export BULK_INGEST_HOST_DIR

python3 - <<'PY'
from pathlib import Path
import os

env_path = Path(".env.prod")
lines = env_path.read_text(encoding="utf-8").splitlines()
updates = {
    "DOMAIN": os.environ["DOMAIN"],
    "ACME_EMAIL": os.environ["ACME_EMAIL"],
    "GOOGLE_API_KEY": os.environ["GOOGLE_API_KEY"],
    "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
    "BULK_INGEST_HOST_DIR": os.environ["BULK_INGEST_HOST_DIR"],
}

db_url = (
    f"postgresql+psycopg://rag_user:{os.environ['POSTGRES_PASSWORD']}"
    "@db:5432/rag_db"
)
updates["DATABASE_URL"] = db_url

out = []
seen = set()
for line in lines:
    if not line or line.startswith("#") or "=" not in line:
        out.append(line)
        continue
    key, _ = line.split("=", 1)
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

echo "[4/7] Preparing bulk ingest directory..."
sudo mkdir -p "${BULK_INGEST_HOST_DIR}"
sudo chown "$(id -u)":"$(id -g)" "${BULK_INGEST_HOST_DIR}"

echo "[5/7] Building and starting services..."
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod pull
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d

echo "[6/7] Service status..."
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod ps

echo "[7/7] Health check..."
curl -fsS -H "Host: ${DOMAIN}" "http://127.0.0.1/health"
echo ""
echo "Done."
echo "Open: https://${DOMAIN}"
