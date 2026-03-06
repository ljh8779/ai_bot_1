#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required but not installed." >&2
  exit 1
fi

if ! git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository: ${ROOT_DIR}" >&2
  exit 1
fi

backup_file=""
if [[ -f "${ENV_FILE}" ]]; then
  backup_file="$(mktemp /tmp/env_prod_backup.XXXXXX)"
  cp "${ENV_FILE}" "${backup_file}"
fi

restore_env() {
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    cp "${backup_file}" "${ENV_FILE}"
    rm -f "${backup_file}"
  fi
}
trap restore_env EXIT

# Keep local production secrets untouched while updating tracked files.
if [[ -f "${ENV_FILE}" ]]; then
  git -C "${ROOT_DIR}" restore .env.prod
fi

git -C "${ROOT_DIR}" pull --rebase "$@"

if [[ -f "${ENV_FILE}" ]]; then
  git -C "${ROOT_DIR}" update-index --skip-worktree .env.prod || true
fi

echo "Safe pull complete."
if [[ -f "${ENV_FILE}" ]]; then
  echo ".env.prod restored and marked with skip-worktree."
  echo "If you need to track .env.prod again: git update-index --no-skip-worktree .env.prod"
fi
