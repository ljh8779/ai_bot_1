from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    db: str = "ok"
    llm: str = "ok"


class IngestTextRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source_name: str = Field(default="manual-input", min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metadata_acl(self) -> "IngestTextRequest":
        for key in ("allowed_departments", "allowed_roles"):
            value = self.metadata.get(key)
            if value is not None:
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f"metadata.{key} must be list[str]")
        return self


class IngestResponse(BaseModel):
    document_id: str
    chunk_count: int


class BulkIngestItem(BaseModel):
    source_path: str
    status: str
    document_id: str | None = None
    chunk_count: int | None = None
    message: str | None = None


class BulkIngestResponse(BaseModel):
    root_directory: str
    scanned_files: int
    ingested_files: int
    skipped_files: int
    failed_files: int
    total_chunks: int
    details: list[BulkIngestItem] = Field(default_factory=list)


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, description="Groupware SSO user identifier")
    user_department: str | None = Field(default=None)
    user_roles: list[str] = Field(default_factory=list)
    history: list[ChatHistoryItem] = Field(default_factory=list)


class SourceChunk(BaseModel):
    document_id: str
    title: str
    source_name: str
    chunk_index: int
    score: float
    excerpt: str


class NotionPageLink(BaseModel):
    url: str
    title: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    html_pages: list[NotionPageLink] = Field(default_factory=list)


class DocumentListItem(BaseModel):
    document_id: str
    title: str
    source_type: str
    source_name: str
    chunk_count: int
    metadata: dict[str, Any]
    created_at: datetime
