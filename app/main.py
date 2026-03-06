import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine, get_db
from app.models import Document, DocumentChunk
from app.schemas import (
    BulkIngestResponse,
    ChatRequest,
    ChatResponse,
    DocumentListItem,
    HealthResponse,
    IngestResponse,
    IngestTextRequest,
)
from app.services.bulk_ingest import ingest_directory
from app.services.file_extract import SUPPORTED_UPLOAD_SUFFIXES, extract_content_from_upload
from app.services.llm import get_available_models, ping_llm
from app.services.rag import answer_question, ingest_text_document

app = FastAPI(title="Groupware RAG Bot API", version="0.1.0")
settings = get_settings()
web_dir = Path(__file__).resolve().parent / "web"
web_dist_dir = web_dir / "dist"
logger = logging.getLogger(__name__)

if web_dist_dir.exists():
    app.mount("/web", StaticFiles(directory=web_dist_dir), name="web")


def _is_model_available(required_model: str, available_models: set[str]) -> bool:
    if required_model in available_models:
        return True
    if f"models/{required_model}" in available_models:
        return True
    if required_model.startswith("models/") and required_model[len("models/") :] in available_models:
        return True
    if ":" not in required_model and f"{required_model}:latest" in available_models:
        return True
    if required_model.endswith(":latest") and required_model[: -len(":latest")] in available_models:
        return True
    return False


def _is_pgvector_duplicate_extension_error(exc: Exception) -> bool:
    message = str(exc)
    return "pg_extension_name_index" in message and "(extname)=(vector)" in message


@app.on_event("startup")
def on_startup() -> None:
    try:
        with engine.begin() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except SQLAlchemyError as exc:
                # Guard against multi-process startup race where two workers
                # concurrently create pgvector extension.
                if not _is_pgvector_duplicate_extension_error(exc):
                    raise
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"))
            conn.execute(
                text(
                    "UPDATE documents "
                    "SET content_hash = md5(id || ':' || source_name || ':' || title) "
                    "WHERE content_hash IS NULL"
                )
            )
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_content_hash_idx ON documents (content_hash)")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_ivfflat "
                    "ON document_chunks USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 100)"
                )
            )
    except Exception as exc:
        raise RuntimeError(
            "Database initialization failed. Ensure pgvector is installed and DB permissions are correct."
        ) from exc


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_status = "ok"
    llm_status = "ok"
    provider = settings.normalized_llm_provider

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        db_status = "down"
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    if not ping_llm():
        llm_status = "down"
        raise HTTPException(status_code=503, detail=f"{provider} LLM service unavailable.")

    required_models = {settings.active_embedding_model, settings.active_chat_model}
    available_models = get_available_models()
    missing_models = sorted(model for model in required_models if not _is_model_available(model, available_models))
    if missing_models:
        llm_status = "down"
        raise HTTPException(
            status_code=503,
            detail=f"{provider} models missing: {', '.join(missing_models)}.",
        )

    return HealthResponse(status="ok", db=db_status, llm=llm_status)


@app.get("/", include_in_schema=False)
def web_home() -> FileResponse:
    index_file = web_dist_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Web UI build not found. Run frontend build first.")
    return FileResponse(index_file)


@app.get("/documents", response_model=list[DocumentListItem])
def list_documents(limit: int = 30, db: Session = Depends(get_db)) -> list[DocumentListItem]:
    safe_limit = min(max(limit, 1), 200)
    chunk_count = func.count(DocumentChunk.id).label("chunk_count")
    stmt = (
        select(
            Document.id,
            Document.title,
            Document.source_type,
            Document.source_name,
            Document.metadata_json,
            Document.created_at,
            chunk_count,
        )
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
        .limit(safe_limit)
    )
    rows = db.execute(stmt).all()
    return [
        DocumentListItem(
            document_id=row.id,
            title=row.title,
            source_type=row.source_type,
            source_name=row.source_name,
            chunk_count=int(row.chunk_count or 0),
            metadata=row.metadata_json or {},
            created_at=row.created_at,
        )
        for row in rows
    ]


@app.post("/documents/text", response_model=IngestResponse)
def ingest_text(payload: IngestTextRequest, db: Session = Depends(get_db)) -> IngestResponse:
    try:
        document_id, chunk_count = ingest_text_document(
            db,
            title=payload.title,
            source_type="manual",
            source_name=payload.source_name,
            content=payload.content,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Ingestion failed due to an internal error.") from exc
    return IngestResponse(document_id=document_id, chunk_count=chunk_count)


@app.post("/documents/file", response_model=IngestResponse)
async def ingest_file(
    title: str = Form(...),
    source_name: str = Form(...),
    metadata_json: str = Form("{}"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> IngestResponse:
    title = title.strip()
    source_name = source_name.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required.")
    if not source_name:
        raise HTTPException(status_code=400, detail="source_name is required.")
    if len(title) > 255:
        raise HTTPException(status_code=400, detail="title must be <= 255 characters.")
    if len(source_name) > 255:
        raise HTTPException(status_code=400, detail="source_name must be <= 255 characters.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        raise HTTPException(
            status_code=400,
            detail=f"This MVP currently supports {supported} only.",
        )

    raw = await file.read()
    max_upload_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(raw) > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max upload size is {settings.max_upload_size_mb} MB.",
        )

    try:
        content = extract_content_from_upload(suffix, raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {exc}") from exc

    try:
        metadata = json.loads(metadata_json)
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must be an object.")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid metadata_json: {exc}") from exc

    try:
        document_id, chunk_count = ingest_text_document(
            db,
            title=title,
            source_type="file",
            source_name=source_name,
            content=content,
            metadata=metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("File ingestion failed. title=%s source_name=%s suffix=%s", title, source_name, suffix)
        raise HTTPException(status_code=500, detail=f"Ingestion failed due to an internal error: {exc}") from exc
    return IngestResponse(document_id=document_id, chunk_count=chunk_count)


@app.post("/documents/bulk", response_model=BulkIngestResponse)
def ingest_bulk_directory(db: Session = Depends(get_db)) -> BulkIngestResponse:
    try:
        return ingest_directory(db, root_dir=Path(settings.bulk_ingest_dir))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Bulk directory ingestion failed. root=%s", settings.bulk_ingest_dir)
        raise HTTPException(status_code=500, detail=f"Bulk ingestion failed due to an internal error: {exc}") from exc


@app.delete("/documents/uploaded")
def delete_uploaded_documents(db: Session = Depends(get_db)) -> dict:
    try:
        chunk_count = (
            db.query(func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.source_type == "file")
            .scalar()
        )
        doc_count = db.query(Document).filter(Document.source_type == "file").delete(synchronize_session=False)
        db.commit()
        logger.info("Uploaded documents deleted. documents=%d chunks=%d", doc_count, chunk_count or 0)
        return {"deleted_documents": int(doc_count or 0), "deleted_chunks": int(chunk_count or 0)}
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to delete uploaded documents.")
        raise HTTPException(status_code=500, detail=f"Uploaded document delete failed: {exc}") from exc


@app.delete("/documents/all")
def delete_all_documents(db: Session = Depends(get_db)) -> dict:
    try:
        chunk_count = db.query(DocumentChunk).delete()
        doc_count = db.query(Document).delete()
        db.commit()
        logger.info("All documents deleted. documents=%d chunks=%d", doc_count, chunk_count)
        return {"deleted_documents": doc_count, "deleted_chunks": chunk_count}
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to delete all documents.")
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}") from exc


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    try:
        answer, sources = answer_question(
            db,
            question=payload.question,
            user_id=payload.user_id,
            user_department=payload.user_department,
            user_roles=payload.user_roles,
            history=[{"role": item.role, "text": item.text} for item in payload.history],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Chat failed.")
        raise HTTPException(status_code=500, detail="Chat failed due to an internal error.") from exc
    return ChatResponse(answer=answer, sources=sources)

