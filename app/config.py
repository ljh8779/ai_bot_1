from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "groupware-rag-bot"
    app_env: str = "dev"
    llm_provider: str = "ollama"
    embedding_provider: str | None = None
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    llm_chat_temperature: float = 0.2
    google_base_url: str = "https://generativelanguage.googleapis.com"
    google_api_key: str | None = None
    google_embedding_model: str = "gemini-embedding-001"
    google_chat_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://ollama:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_chat_model: str = "qwen2.5:7b"
    database_url: str = "postgresql+psycopg://rag_user:rag_pass@localhost:5432/rag_db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    embedding_dimensions: int = 768
    chunk_size: int = 1500
    chunk_overlap: int = 300
    ingest_embedding_batch_size: int = 64
    max_context_chunks: int = 5
    search_candidate_multiplier: int = 4
    allow_general_fallback: bool = True
    general_fallback_min_score: float = 0.70
    max_upload_size_mb: int = 20
    bulk_ingest_dir: str = "/bulk_ingest"
    bulk_ingest_max_files: int = 1000
    bulk_ingest_zip_member_limit: int = 2000
    bulk_ingest_details_limit: int = 300
    pdf_ocr_enabled: bool = True
    pdf_ocr_max_pages: int = 20
    pdf_ocr_dpi: int = 200
    pdf_ocr_fallback_min_chars: int = 40
    ocr_tesseract_lang: str = "kor+eng"
    notion_api_key: str | None = None
    hf_embedding_model: str = "jhgan/ko-sroberta-multitask"

    # Hybrid search & reranking
    hybrid_search_enabled: bool = True
    bm25_weight: float = 0.3
    rerank_enabled: bool = False
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_top_n: int = 5
    rerank_candidates: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def normalized_llm_provider(self) -> str:
        return self.llm_provider.strip().lower()

    @property
    def normalized_embedding_provider(self) -> str:
        provider = self.embedding_provider or self.llm_provider
        return provider.strip().lower()

    @property
    def active_embedding_model(self) -> str:
        if self.normalized_embedding_provider == "google":
            return self.google_embedding_model
        if self.normalized_embedding_provider == "huggingface":
            return self.hf_embedding_model
        return self.ollama_embedding_model

    @property
    def active_chat_model(self) -> str:
        if self.normalized_llm_provider == "google":
            return self.google_chat_model
        return self.ollama_chat_model

    @model_validator(mode="after")
    def validate_ranges(self) -> "Settings":
        if self.normalized_llm_provider not in {"google", "ollama"}:
            raise ValueError("LLM_PROVIDER must be one of: google, ollama")
        if self.normalized_embedding_provider not in {"google", "ollama", "huggingface"}:
            raise ValueError("EMBEDDING_PROVIDER must be one of: google, ollama, huggingface")
        if (
            self.normalized_llm_provider == "google" or self.normalized_embedding_provider == "google"
        ) and not (self.google_api_key or "").strip():
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=google or EMBEDDING_PROVIDER=google")
        if self.normalized_embedding_provider == "huggingface" and not self.hf_embedding_model.strip():
            raise ValueError("HF_EMBEDDING_MODEL is required when EMBEDDING_PROVIDER=huggingface")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be > 0")
        if self.llm_max_retries < 0:
            raise ValueError("LLM_MAX_RETRIES must be >= 0")
        if not 0 <= self.llm_chat_temperature <= 2:
            raise ValueError("LLM_CHAT_TEMPERATURE must be in [0, 2]")
        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE must be > 0")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE")
        if self.max_context_chunks <= 0:
            raise ValueError("MAX_CONTEXT_CHUNKS must be > 0")
        if self.search_candidate_multiplier <= 0:
            raise ValueError("SEARCH_CANDIDATE_MULTIPLIER must be > 0")
        if not 0 <= self.general_fallback_min_score <= 1:
            raise ValueError("GENERAL_FALLBACK_MIN_SCORE must be in [0, 1]")
        if self.ingest_embedding_batch_size <= 0:
            raise ValueError("INGEST_EMBEDDING_BATCH_SIZE must be > 0")
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be > 0")
        if self.max_upload_size_mb <= 0:
            raise ValueError("MAX_UPLOAD_SIZE_MB must be > 0")
        if self.bulk_ingest_max_files <= 0:
            raise ValueError("BULK_INGEST_MAX_FILES must be > 0")
        if self.bulk_ingest_zip_member_limit <= 0:
            raise ValueError("BULK_INGEST_ZIP_MEMBER_LIMIT must be > 0")
        if self.bulk_ingest_details_limit <= 0:
            raise ValueError("BULK_INGEST_DETAILS_LIMIT must be > 0")
        if self.pdf_ocr_max_pages <= 0:
            raise ValueError("PDF_OCR_MAX_PAGES must be > 0")
        if self.pdf_ocr_dpi < 72:
            raise ValueError("PDF_OCR_DPI must be >= 72")
        if self.pdf_ocr_fallback_min_chars < 0:
            raise ValueError("PDF_OCR_FALLBACK_MIN_CHARS must be >= 0")
        if not self.ocr_tesseract_lang.strip():
            raise ValueError("OCR_TESSERACT_LANG must not be empty")
        if not 0 <= self.bm25_weight <= 1:
            raise ValueError("BM25_WEIGHT must be in [0, 1]")
        if self.rerank_top_n <= 0:
            raise ValueError("RERANK_TOP_N must be > 0")
        if self.rerank_candidates <= 0:
            raise ValueError("RERANK_CANDIDATES must be > 0")
        if self.rerank_candidates < self.rerank_top_n:
            raise ValueError("RERANK_CANDIDATES must be >= RERANK_TOP_N")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
