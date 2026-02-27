# Groupware RAG Bot

This project is a RAG chatbot MVP for company groupware.
It now supports both local and cloud LLM providers:
- `ollama` (on-prem/local)
- `google` (Gemini API, free tier available)

## What Is Implemented

- Document ingestion
  - `POST /documents/text` for manual text
  - `POST /documents/file` for `.txt`, `.md`, `.pdf`, `.pptx`, image files (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`)
  - `POST /documents/bulk` for directory batch ingestion (includes `.zip` internal supported files)
- Retrieval-augmented chat
  - `POST /chat` returns answer + source chunks
- Access control filtering
  - `allowed_departments`, `allowed_roles` metadata
- Web console
  - `http://localhost:8000/` for ingest/testing without Swagger

## Stack

- API: FastAPI
- Frontend: React + Vite (built static assets served by FastAPI)
- Vector DB: PostgreSQL + pgvector
- LLM provider: `LLM_PROVIDER=ollama|google`
- Ollama models (local): `nomic-embed-text`, `qwen2.5:7b`
- Google models (cloud): `gemini-embedding-001`, `gemini-2.5-flash`

## Quick Start

1. Create `.env`

```bash
cp .env.example .env
```

2. Configure cloud mode (Google, recommended for free-tier)

Edit `.env`:

```bash
LLM_PROVIDER=google
GOOGLE_API_KEY=your_google_ai_api_key_here
GOOGLE_EMBEDDING_MODEL=gemini-embedding-001
GOOGLE_CHAT_MODEL=gemini-2.5-flash
```

3. Start infrastructure

```bash
docker compose up -d db
```

4. Start API

```bash
docker compose up --build -d api
```

5. (Optional) Local mode with Ollama

If you want local inference instead of cloud, set:

```bash
LLM_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=qwen2.5:7b
```

Then run:

```bash
docker compose up -d db ollama
docker exec rag_ollama ollama pull nomic-embed-text
docker exec rag_ollama ollama pull qwen2.5:7b
docker compose up --build -d api
```

6. Open UI

- Web console: `http://localhost:8000/`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## Frontend Dev (Vite)

```bash
cd app/web
npm install
npm run dev
```

- Vite dev server: `http://localhost:5173`
- Production bundle is generated in `app/web/dist` during Docker build.

## Notes

- If using Google provider, `GOOGLE_API_KEY` is required.
- If using Ollama outside Docker, set `OLLAMA_BASE_URL` in `.env`.
  - Example: `http://host.docker.internal:11434`
- `EMBEDDING_DIMENSIONS` must match your embedding model output dimension.
  - `nomic-embed-text` default is `768`.
- PDF/image OCR fallback is enabled by default for scan/image-only files.
  - `PDF_OCR_ENABLED=true`
  - `PDF_OCR_MAX_PAGES=20`
  - `PDF_OCR_DPI=200`
  - `PDF_OCR_FALLBACK_MIN_CHARS=40`
  - `OCR_TESSERACT_LANG=kor+eng`
- Bulk directory ingestion defaults:
  - `BULK_INGEST_DIR=/bulk_ingest`
  - `BULK_INGEST_MAX_FILES=1000`
  - `BULK_INGEST_ZIP_MEMBER_LIMIT=2000`
  - `BULK_INGEST_DETAILS_LIMIT=300`
  - In Docker, host path `C:/Users/ljh87/Downloads/ai_bot_folder` is bound to `/bulk_ingest`.

## API Examples

### Ingest Text

`POST /documents/text`

```json
{
  "title": "Attendance Policy 2026",
  "source_name": "HR-Wiki",
  "content": "Employees can carry over annual leave under ...",
  "metadata": {
    "allowed_departments": ["HR", "FIN"],
    "allowed_roles": ["manager", "hr_admin"]
  }
}
```

### Ask Chat

`POST /chat`

```json
{
  "question": "What is the annual leave carry-over rule?",
  "user_id": "u-1001",
  "user_department": "HR",
  "user_roles": ["manager"]
}
```

### Bulk Ingest Directory

`POST /documents/bulk`

No request body required. The server scans `BULK_INGEST_DIR` recursively and ingests supported files.
If a `.zip` is found, supported files inside the archive are also ingested.

## Main Tunables

- `LLM_PROVIDER`
- `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_CHAT_TEMPERATURE`
- `GOOGLE_CHAT_MODEL`, `GOOGLE_EMBEDDING_MODEL`, `GOOGLE_API_KEY`
- `OLLAMA_BASE_URL`
- `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `CHUNK_SIZE`, `CHUNK_OVERLAP`
- `MAX_CONTEXT_CHUNKS`
- `INGEST_EMBEDDING_BATCH_SIZE`
- `SEARCH_CANDIDATE_MULTIPLIER`
- `MAX_UPLOAD_SIZE_MB`
- `PDF_OCR_ENABLED`, `PDF_OCR_MAX_PAGES`, `PDF_OCR_DPI`
- `PDF_OCR_FALLBACK_MIN_CHARS`, `OCR_TESSERACT_LANG`

## Next Extensions

- PDF/DOCX/HWP parsers
- SSO middleware for auto-claims injection
- Audit logs and sensitive-data masking
- Reranker for retrieval precision
