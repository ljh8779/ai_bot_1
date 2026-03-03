import hashlib
import math
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk
from app.schemas import SourceChunk
from app.services.llm import generate_answer, get_embedding, get_embeddings
from app.utils import chunk_text, normalize_text

settings = get_settings()
FOLLOWUP_MARKERS = re.compile(
    r"(그거|그건|그럼|이거|저거|그쪽|거기|그건데|그거는|우리회사도|우리회사에서도|그럼 우리)",
    flags=re.IGNORECASE,
)
MAX_HISTORY_ITEMS = 8
MAX_HISTORY_TEXT_LEN = 700


def _is_document_allowed(
    metadata: dict[str, Any] | None,
    user_department: str | None,
    user_role_set: set[str],
) -> bool:
    metadata = metadata or {}
    allowed_departments = metadata.get("allowed_departments", [])
    allowed_roles = metadata.get("allowed_roles", [])

    department_ok = not allowed_departments or (user_department in allowed_departments)
    role_ok = not allowed_roles or bool(user_role_set.intersection(set(allowed_roles)))
    return department_ok and role_ok


def _content_hash(content: str) -> str:
    normalized = normalize_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chunk_count_by_document_id(db: Session, document_id: str) -> int:
    chunk_count = db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id))
    return int(chunk_count or 0)


def ingest_text_document(
    db: Session,
    *,
    title: str,
    source_type: str,
    source_name: str,
    content: str,
    metadata: dict[str, Any],
) -> tuple[str, int]:
    chunks = list(chunk_text(content, settings.chunk_size, settings.chunk_overlap))
    if not chunks:
        raise ValueError("No chunks produced from content.")

    content_hash = _content_hash(content)
    existing = db.scalar(select(Document).where(Document.content_hash == content_hash).limit(1))
    if existing:
        return existing.id, _chunk_count_by_document_id(db, existing.id)

    embeddings = get_embeddings(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError("Embedding size mismatch during ingestion.")

    try:
        doc = Document(
            title=title,
            source_type=source_type,
            source_name=source_name,
            content_hash=content_hash,
            metadata_json=metadata,
        )
        db.add(doc)
        db.flush()

        db.add_all(
            [
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=text_chunk,
                    embedding=embeddings[idx],
                )
                for idx, text_chunk in enumerate(chunks)
            ]
        )
        db.commit()
        return doc.id, len(chunks)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Document).where(Document.content_hash == content_hash).limit(1))
        if existing:
            return existing.id, _chunk_count_by_document_id(db, existing.id)
        raise
    except Exception:
        db.rollback()
        raise


def _distance_score(distance: float) -> float:
    return max(0.0, 1.0 - distance)


def _to_source_chunk(
    *,
    doc: Document,
    chunk: DocumentChunk,
    distance: float,
) -> SourceChunk:
    return SourceChunk(
        document_id=doc.id,
        title=doc.title,
        source_name=doc.source_name,
        chunk_index=chunk.chunk_index,
        score=round(_distance_score(distance), 4),
        excerpt=chunk.content[:220],
    )


def _candidate_limit() -> int:
    return settings.max_context_chunks * settings.search_candidate_multiplier


def _strip_bracket_citations(text: str) -> str:
    # Remove bracket-style numeric citations like [1], [2] from model output.
    cleaned = re.sub(r"(?:(?<=\s)|^)\[\d+\](?=\s|$|[.,!?])", "", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _general_fallback_answer(*, question: str, user_id: str) -> str:
    system_prompt = (
        "You are a helpful Korean AI assistant for employees. "
        "Respond naturally and politely in Korean, with a friendly tone. "
        "If the question needs real-time/live data (for example current weather, stock price, live traffic), "
        "do not guess. Clearly say you cannot verify live data right now and suggest a practical way to check. "
        "Do not mention internal system policy unless asked."
    )
    user_prompt = (
        f"User: {user_id}\n"
        f"Question: {question}\n\n"
        "답변은 너무 딱딱하지 않게, 이해하기 쉽게 한국어 존댓말로 작성해 주세요."
    )
    return _strip_bracket_citations(generate_answer(system_prompt, user_prompt))


def _normalize_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    if not history:
        return []
    cleaned: list[dict[str, str]] = []
    for item in history[-MAX_HISTORY_ITEMS:]:
        role = str(item.get("role") or "").strip().lower()
        text = normalize_text(str(item.get("text") or "")).strip()
        if role not in {"user", "assistant"} or not text:
            continue
        cleaned.append({"role": role, "text": text[:MAX_HISTORY_TEXT_LEN]})
    return cleaned


def _latest_history_text(history: list[dict[str, str]], role: str) -> str:
    for item in reversed(history):
        if item.get("role") == role:
            return item.get("text", "")
    return ""


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def _should_use_history_context(question: str, history: list[dict[str, str]]) -> bool:
    if not history:
        return False

    last_user = _latest_history_text(history, "user")
    last_assistant = _latest_history_text(history, "assistant")
    candidates = [text for text in [last_user, last_assistant] if text]
    if not candidates:
        return False

    embeddings = get_embeddings([question, *candidates])
    if len(embeddings) != (1 + len(candidates)):
        return False

    question_vec = embeddings[0]
    similarity = max(_cosine_similarity(question_vec, vec) for vec in embeddings[1:])
    has_followup_marker = bool(FOLLOWUP_MARKERS.search(question))
    looks_short = len(question) <= 16

    if has_followup_marker and similarity >= 0.25:
        return True
    if looks_short and similarity >= 0.45:
        return True
    return similarity >= 0.78


def _rewrite_followup_question(*, question: str, history: list[dict[str, str]], user_id: str) -> str:
    history_text = "\n".join(
        [f"{idx + 1}. {item['role']}: {item['text']}" for idx, item in enumerate(history[-4:])]
    )
    system_prompt = (
        "You rewrite follow-up chat questions into standalone Korean questions. "
        "Return only one rewritten question sentence. "
        "If rewriting is not possible, return the original question unchanged."
    )
    user_prompt = (
        f"User: {user_id}\n"
        f"Recent conversation:\n{history_text}\n\n"
        f"Original question: {question}\n\n"
        "Output rules: One standalone Korean question only. No explanation."
    )
    rewritten = _strip_bracket_citations(generate_answer(system_prompt, user_prompt))
    rewritten = rewritten.strip().strip('"').strip("'")
    if not rewritten:
        return question
    return rewritten[:4000]


def _resolve_effective_question(*, question: str, user_id: str, history: list[dict[str, str]] | None) -> str:
    normalized_question = normalize_text(question).strip()
    if not normalized_question:
        return question

    cleaned_history = _normalize_history(history)
    if not cleaned_history:
        return normalized_question

    try:
        if not _should_use_history_context(normalized_question, cleaned_history):
            return normalized_question
        return _rewrite_followup_question(
            question=normalized_question,
            history=cleaned_history,
            user_id=user_id,
        )
    except Exception:
        return normalized_question


def _is_low_confidence_retrieval(sources: list[SourceChunk]) -> bool:
    if not sources:
        return True
    best_score = max(source.score for source in sources)
    return best_score < settings.general_fallback_min_score


def _search_chunks(
    db: Session,
    *,
    question_embedding: list[float],
    user_department: str | None,
    user_roles: list[str],
) -> list[SourceChunk]:
    distance = DocumentChunk.embedding.cosine_distance(question_embedding).label("distance")
    stmt = (
        select(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .order_by(distance.asc())
        .limit(_candidate_limit())
    )
    rows = db.execute(stmt).all()
    user_role_set = set(user_roles)

    selected: list[SourceChunk] = []
    for chunk, doc, dist in rows:
        if not _is_document_allowed(doc.metadata_json, user_department, user_role_set):
            continue
        selected.append(
            _to_source_chunk(
                doc=doc,
                chunk=chunk,
                distance=float(dist),
            )
        )
        if len(selected) >= settings.max_context_chunks:
            break
    return selected


def answer_question(
    db: Session,
    *,
    question: str,
    user_id: str,
    user_department: str | None,
    user_roles: list[str],
    history: list[dict[str, str]] | None = None,
) -> tuple[str, list[SourceChunk]]:
    effective_question = _resolve_effective_question(question=question, user_id=user_id, history=history)
    question_embedding = get_embedding(effective_question)
    sources = _search_chunks(
        db,
        question_embedding=question_embedding,
        user_department=user_department,
        user_roles=user_roles,
    )
    if not sources:
        if settings.allow_general_fallback:
            return _general_fallback_answer(question=effective_question, user_id=user_id), []
        return "참고할 사내 문서를 찾지 못했어요. 질문을 조금 더 구체적으로 적어 주시면 다시 찾아볼게요.", []
    if settings.allow_general_fallback and _is_low_confidence_retrieval(sources):
        return _general_fallback_answer(question=effective_question, user_id=user_id), []

    context_lines = []
    for idx, source in enumerate(sources, start=1):
        context_lines.append(
            f"[{idx}] title={source.title} / source={source.source_name} / content={source.excerpt}"
        )
    context_text = "\n".join(context_lines)

    system_prompt = (
        "You are an enterprise groupware AI assistant. "
        "For company/internal questions, prioritize and rely on provided context. "
        "If context is clearly unrelated to the question and the question is general common knowledge, "
        "you may answer from general knowledge in Korean. "
        "For real-time/live data questions (weather, stock, traffic, breaking news), do not guess. "
        "Say you cannot verify live data right now and suggest a practical way to check. "
        "Respond naturally and politely in Korean. "
        "Do not include bracket citations like [1], [2] in the answer."
    )
    user_prompt = (
        f"User: {user_id}\n"
        f"Question: {question}\n"
        f"Interpreted question for retrieval: {effective_question}\n\n"
        f"Context:\n{context_text}\n\n"
        "Requirements: Respond concisely in Korean with a friendly, non-rigid tone. "
        "Do not include bracket citations like [1], [2]."
    )
    answer = _strip_bracket_citations(generate_answer(system_prompt, user_prompt))
    return answer, sources
