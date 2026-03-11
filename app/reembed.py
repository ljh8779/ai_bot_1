from app.config import get_settings
from app.db import SessionLocal
from app.models import DocumentChunk
from app.services.llm import get_embeddings


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    updated = 0

    try:
        chunks = db.query(DocumentChunk).order_by(DocumentChunk.created_at.asc(), DocumentChunk.id.asc()).all()
        batch_size = max(1, settings.ingest_embedding_batch_size)

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings = get_embeddings([chunk.content for chunk in batch])
            for chunk, embedding in zip(batch, embeddings, strict=True):
                chunk.embedding = embedding
                updated += 1
            db.commit()
            print(f"reembedded {updated}/{len(chunks)} chunks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
