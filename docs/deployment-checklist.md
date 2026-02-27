# Production Deployment Checklist

## Before Deploy

- [ ] Rotate and replace any leaked API keys.
- [ ] Create `.env.prod` from `.env.prod.example`.
- [ ] Set `DOMAIN`, `ACME_EMAIL`, `GOOGLE_API_KEY`.
- [ ] Set strong `POSTGRES_PASSWORD`.
- [ ] Confirm `DATABASE_URL` matches DB credentials.
- [ ] Create host ingest directory (default: `/opt/ai_bot_folder`).
- [ ] Put only intended files in bulk ingest directory.

## Server Hardening

- [ ] Restrict SSH (`22`) to admin IP.
- [ ] Open only `80/443` publicly.
- [ ] Enable UFW or cloud firewall rules.
- [ ] Enable automatic security updates for OS.
- [ ] Configure log retention and disk alerts.

## Deploy

- [ ] `cp .env.prod.example .env.prod`
- [ ] Fill all required values in `.env.prod`
- [ ] Run: `bash scripts/deploy_prod.sh`
- [ ] Verify: `curl http://localhost/health`

## Post-Deploy Validation

- [ ] Open `https://<DOMAIN>` and confirm UI loads.
- [ ] Upload a sample document and confirm ingestion.
- [ ] Run bulk ingest from UI (`일괄처리`) and verify response.
- [ ] Ask a test question and verify RAG sources are returned.

## Operations

- [ ] Regular DB backup job configured.
- [ ] Monitor container restarts and API health.
- [ ] Rotate credentials periodically.
- [ ] Keep Docker image and base OS updated.

